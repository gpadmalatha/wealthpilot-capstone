"""Fallback chain for the credit-bureau pull: live sources in order, then the last good (cached) report, then a human.

The caller always learns WHICH source answered, so a degraded answer is never mistaken for a live one.
"""
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from capstone.observability.tracing import span
from capstone.reliability.circuit_breaker import CircuitBreaker, CircuitOpenError
from capstone.reliability.retries import SourceUnavailableError, call_with_retries
from capstone.settings import get_settings
from capstone.tools.lookups import ApplicantNotFoundError, get_bureau_report

logger = logging.getLogger(__name__)

LIVE, CACHE, UNAVAILABLE = "live", "cache", "unavailable"
RETRYABLE = (SourceUnavailableError, TimeoutError, ConnectionError)


@dataclass
class BureauOutcome:
  status: str  # live | cache | unavailable
  source: str  # which source answered, or 'none'
  report: Optional[dict] = None
  attempts: list[str] = field(default_factory=list)  # human-readable log of what was tried
  cache_age_hours: Optional[float] = None
  used_fallback: bool = False  # True when the answer came from a backup source or the cache, not the primary source


class BureauSource:
  def __init__(self, name: str, fetch: Callable[[str], dict], breaker: Optional[CircuitBreaker] = None):
    self.name = name
    self.fetch = fetch
    self.breaker = breaker or CircuitBreaker(name)


def _default_cache_path() -> Path:
  folder = get_settings().project_root / "runtime"
  folder.mkdir(exist_ok=True)
  return folder / "bureau_cache.json"


class ResilientBureau:
  def __init__(self, sources: list[BureauSource], cache_path: Optional[Path] = None, *, sleep=None):
    self.sources = sources
    self._cache_path = cache_path
    self._sleep = sleep

  def _cache(self) -> dict:
    path = self._cache_path or _default_cache_path()
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

  def _remember(self, applicant_id: str, report: dict) -> None:
    path = self._cache_path or _default_cache_path()
    cache = self._cache()
    cache[applicant_id] = {"report": report, "cached_at": datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(cache), encoding="utf-8")

  def _cached(self, applicant_id: str) -> tuple[Optional[dict], Optional[float]]:
    entry = self._cache().get(applicant_id)
    if not entry:
      return None, None
    age = datetime.now(timezone.utc) - datetime.fromisoformat(entry["cached_at"])
    if age > timedelta(hours=get_settings().bureau_cache_max_age_hours):
      return None, None  # too old to rely on
    return entry["report"], round(age.total_seconds() / 3600, 2)

  def fetch(self, applicant_id: str) -> BureauOutcome:
    attempts: list[str] = []
    for position, source in enumerate(self.sources):
      with span(f"bureau:{source.name}", kind="dependency", applicant_id=applicant_id) as attrs:
        try:
          kwargs = {"sleep": self._sleep} if self._sleep else {}
          report = source.breaker.call(
              lambda: call_with_retries(lambda: source.fetch(applicant_id), label=source.name, **kwargs),
              counts_as_failure=RETRYABLE,
          )
        except CircuitOpenError:
          attempts.append(f"{source.name}: circuit open, skipped")
          attrs.update(result="circuit_open", breaker_state=source.breaker.state)
          continue
        except RETRYABLE as error:
          attempts.append(f"{source.name}: failed after retries ({type(error).__name__})")
          attrs.update(result="failed", breaker_state=source.breaker.state)
          continue
        except ApplicantNotFoundError:
          attempts.append(f"{source.name}: applicant not found")
          attrs.update(result="not_found", breaker_state=source.breaker.state)
          return BureauOutcome(UNAVAILABLE, "none", attempts=attempts)  # a missing record is not an outage; do not fall back
        used_fallback = position > 0  # an answer from any source after the first is a degraded path
        attrs.update(result="ok", breaker_state=source.breaker.state, used_fallback=used_fallback)
        attempts.append(f"{source.name}: ok")
        self._remember(applicant_id, report)
        return BureauOutcome(LIVE, source.name, report, attempts, used_fallback=used_fallback)

    report, age = self._cached(applicant_id)
    with span("bureau:cache", kind="dependency", applicant_id=applicant_id) as attrs:
      attrs.update(result="hit" if report else "miss", used_fallback=bool(report))
    if report:
      attempts.append(f"cache: last good report, {age} hours old")
      return BureauOutcome(CACHE, "cache", report, attempts, age, used_fallback=True)
    attempts.append("cache: no usable report")
    return BureauOutcome(UNAVAILABLE, "none", None, attempts)


_default: Optional[ResilientBureau] = None


def default_bureau() -> ResilientBureau:
  """Process-wide instance, so breaker state is shared by every request in the process."""
  global _default
  if _default is None:
    _default = ResilientBureau([BureauSource("bureau_primary", get_bureau_report)])
  return _default

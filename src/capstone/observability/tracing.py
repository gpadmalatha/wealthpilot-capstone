"""Request tracing: one trace per underwriting request, nested spans for nodes, tools and model calls.

Spans are written as JSON lines to runtime/traces/<trace_id>.jsonl. Only names, ids, timings, statuses and small
attributes are recorded: never prompts, applicant names or other personal data. A different sink (for example a
LangFuse exporter) can be plugged in with set_sink().
"""
import functools
import json
import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from capstone.settings import get_settings

logger = logging.getLogger(__name__)

_trace_id: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)
_span_id: ContextVar[Optional[str]] = ContextVar("span_id", default=None)
_attrs: ContextVar[Optional[dict]] = ContextVar("span_attrs", default=None)

MAX_ERROR_CHARS = 200
Sink = Callable[[dict], None]


def _file_sink(event: dict) -> None:
  folder = get_settings().project_root / "runtime" / "traces"
  folder.mkdir(parents=True, exist_ok=True)
  with (folder / f"{event['trace_id']}.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(event, default=str) + "\n")


_sink: Sink = _file_sink


def set_sink(sink: Optional[Sink]) -> None:
  """Replace where spans go (None restores the file sink)."""
  global _sink
  _sink = sink or _file_sink


def current_trace_id() -> Optional[str]:
  return _trace_id.get()


@contextmanager
def start_trace(name: str, **attrs: Any) -> Iterator[str]:
  """Open a trace (or join the active one) and a root span around the request."""
  existing = _trace_id.get()
  token = None if existing else _trace_id.set(f"{name.replace(' ', '_')}-{uuid.uuid4().hex[:10]}")
  try:
    with span(name, kind="request", **attrs):
      yield _trace_id.get()
  finally:
    if token is not None:
      _trace_id.reset(token)


@contextmanager
def span(name: str, kind: str = "step", **attrs: Any) -> Iterator[dict]:
  """Time a block. The yielded dict collects extra attributes; an exception marks the span as an error and re-raises."""
  trace_id = _trace_id.get()
  if not trace_id or not get_settings().tracing_enabled:
    yield attrs
    return
  span_id = uuid.uuid4().hex[:8]
  parent_id = _span_id.get()
  token = _span_id.set(span_id)
  attrs_token = _attrs.set(attrs)
  started = time.perf_counter()
  event = {"trace_id": trace_id, "span_id": span_id, "parent_id": parent_id, "name": name, "kind": kind,
           "started_at": datetime.now(timezone.utc).isoformat(), "attrs": attrs, "status": "ok"}
  try:
    yield attrs
  except Exception as error:
    # a human pause is a normal outcome, not a failure
    event["status"] = "interrupted" if type(error).__name__ == "GraphInterrupt" else "error"
    event["error"] = f"{type(error).__name__}: {str(error)[:MAX_ERROR_CHARS]}"
    raise
  finally:
    event["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
    _span_id.reset(token)
    _attrs.reset(attrs_token)
    try:
      _sink(event)
    except Exception:  # tracing must never break the request
      logger.warning("trace sink failed", exc_info=True)


def annotate(**attrs: Any) -> None:
  """Add attributes to the span that is currently open (no-op outside a trace)."""
  current = _attrs.get()
  if current is not None:
    current.update(attrs)


def traced(name: str, kind: str = "step") -> Callable:
  """Decorator: run the function inside a span."""
  def decorate(function: Callable) -> Callable:
    @functools.wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
      with span(name, kind=kind):
        return function(*args, **kwargs)
    return wrapper
  return decorate


def read_trace(path: Path) -> list[dict]:
  return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

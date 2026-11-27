"""Request tracing: one trace per underwriting request, nested spans for nodes, tools and model calls.

Every span is written two ways:
  * as a JSON line in runtime/traces/<trace_id>.jsonl (our own sink, used by scripts/trace_kpis.py), and
  * as an OpenTelemetry span (see observability/otel.py), exported to runtime/otel/spans.jsonl, so any
    OpenTelemetry backend (Jaeger, Grafana Tempo, Langfuse's OTLP endpoint) can be attached by configuration.
Spans carry a session_id and a user_id. Only names, ids, timings, statuses, token counts, cost and small attributes
are recorded: never prompts, applicant names or other personal data. A different sink can be plugged in with set_sink().
"""
import functools
import json
import logging
import time
import uuid
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from capstone.settings import get_settings

logger = logging.getLogger(__name__)

_trace_id: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)
_span_id: ContextVar[Optional[str]] = ContextVar("span_id", default=None)
_attrs: ContextVar[Optional[dict]] = ContextVar("span_attrs", default=None)
_session_id: ContextVar[Optional[str]] = ContextVar("session_id", default=None)
_user_id: ContextVar[Optional[str]] = ContextVar("user_id", default=None)
_otel_tracer: Any = None  # set by observability.otel.enable_otel()

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


def set_otel_tracer(tracer: Any) -> None:
  """Mirror every span to this OpenTelemetry tracer (None switches the mirror off)."""
  global _otel_tracer
  _otel_tracer = tracer


def _ensure_otel() -> None:
  """Turn the OpenTelemetry mirror on the first time a trace starts (unless OTEL_ENABLED=false)."""
  if _otel_tracer is None and get_settings().otel_enabled:
    from capstone.observability.otel import enable_otel
    enable_otel()


def current_trace_id() -> Optional[str]:
  return _trace_id.get()


def current_session_id() -> Optional[str]:
  return _session_id.get()


def current_user_id() -> Optional[str]:
  return _user_id.get()


@contextmanager
def start_trace(name: str, *, session_id: Optional[str] = None, user_id: Optional[str] = None, **attrs: Any) -> Iterator[str]:
  """Open a trace (or join the active one) and a root span around the request.

  session_id groups the requests of one conversation or case; user_id says who asked ('system' for batch jobs).
  A trace that joins an active one keeps the ids already set unless new ones are passed.
  """
  _ensure_otel()
  existing = _trace_id.get()
  token = None if existing else _trace_id.set(f"{name.replace(' ', '_')}-{uuid.uuid4().hex[:10]}")
  session_token = _session_id.set(session_id) if session_id else (_session_id.set(_trace_id.get()) if _session_id.get() is None else None)
  user_token = _user_id.set(user_id) if user_id else (_user_id.set("anonymous") if _user_id.get() is None else None)
  try:
    with span(name, kind="request", **attrs):
      yield _trace_id.get()
  finally:
    if user_token is not None:
      _user_id.reset(user_token)
    if session_token is not None:
      _session_id.reset(session_token)
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
           "session_id": _session_id.get(), "user_id": _user_id.get(),
           "started_at": datetime.now(timezone.utc).isoformat(), "attrs": attrs, "status": "ok"}
  mirror = _otel_tracer.start_as_current_span(name, record_exception=False, set_status_on_exception=False) if _otel_tracer else nullcontext()
  with mirror as otel_span:
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
      if otel_span is not None:
        _copy_to_otel(otel_span, event)
      try:
        _sink(event)
      except Exception:  # tracing must never break the request
        logger.warning("trace sink failed", exc_info=True)


def _copy_to_otel(otel_span: Any, event: dict) -> None:
  """Copy our span record onto the OpenTelemetry span (flat attributes, session.id / user.id as in the OTel conventions)."""
  try:
    otel_span.set_attribute("capstone.kind", event["kind"])
    otel_span.set_attribute("capstone.trace_id", event["trace_id"])
    otel_span.set_attribute("capstone.status", event["status"])
    otel_span.set_attribute("capstone.duration_ms", event["duration_ms"])
    if event.get("session_id"):
      otel_span.set_attribute("session.id", event["session_id"])
    if event.get("user_id"):
      otel_span.set_attribute("user.id", event["user_id"])
    for key, value in event["attrs"].items():
      if value is not None:
        otel_span.set_attribute(f"capstone.{key}", value if isinstance(value, (bool, int, float, str)) else str(value))
    if event["status"] == "error":
      from opentelemetry.trace import Status, StatusCode
      otel_span.set_status(Status(StatusCode.ERROR, event.get("error", "")))
  except Exception:  # the mirror must never break the request
    logger.warning("OpenTelemetry mirror failed", exc_info=True)


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

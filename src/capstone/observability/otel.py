"""OpenTelemetry export for request traces.

tracing.span() mirrors every span to the tracer set here. By default the spans go to a JSON-lines file
(runtime/otel/spans.jsonl, one OpenTelemetry span per line). To send them to a collector or to Langfuse's OTLP
endpoint instead, install the OTLP exporter and set OTEL_EXPORTER_OTLP_ENDPOINT (and OTEL_EXPORTER_OTLP_HEADERS):
no code change is needed, because the exporter is chosen in build_exporter().
"""
import logging
import os
from pathlib import Path
from typing import Optional

from capstone.observability.tracing import set_otel_tracer
from capstone.settings import get_settings

logger = logging.getLogger(__name__)
SERVICE_NAME = "wealthpilot"
_enabled = False


def default_span_file() -> Path:
  return get_settings().project_root / "runtime" / "otel" / "spans.jsonl"


def build_exporter(span_file: Optional[Path] = None):
  """OTLP over HTTP when an endpoint is configured and the exporter is installed, otherwise a JSON-lines file."""
  if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
    try:
      from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
      return OTLPSpanExporter()
    except ImportError:
      logger.warning("OTEL_EXPORTER_OTLP_ENDPOINT is set but opentelemetry-exporter-otlp-proto-http is not installed; writing spans to a file instead")
  from opentelemetry.sdk.trace.export import ConsoleSpanExporter
  path = span_file or default_span_file()
  path.parent.mkdir(parents=True, exist_ok=True)
  handle = path.open("a", encoding="utf-8")
  return ConsoleSpanExporter(out=handle, formatter=lambda span: span.to_json(indent=None) + "\n")


def enable_otel(span_file: Optional[Path] = None) -> bool:
  """Switch the OpenTelemetry mirror on. Safe to call more than once. Returns False when the SDK is missing."""
  global _enabled
  if _enabled:
    return True
  try:
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
  except ImportError:
    logger.warning("opentelemetry-sdk is not installed; spans go to runtime/traces only")
    return False
  provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
  provider.add_span_processor(SimpleSpanProcessor(build_exporter(span_file)))
  set_otel_tracer(provider.get_tracer("capstone"))
  _enabled = True
  return True


def disable_otel() -> None:
  global _enabled
  set_otel_tracer(None)
  _enabled = False

"""Logging setup: every log line carries the active trace id, so logs and traces join up."""
import logging

from capstone.observability.tracing import current_trace_id

LOG_FORMAT = "%(asctime)s %(levelname)s [trace=%(trace_id)s] %(name)s: %(message)s"


class TraceIdFilter(logging.Filter):
  def filter(self, record: logging.LogRecord) -> bool:
    record.trace_id = current_trace_id() or "-"
    return True


def configure_logging(level: int = logging.INFO) -> None:
  handler = logging.StreamHandler()
  handler.setFormatter(logging.Formatter(LOG_FORMAT))
  handler.addFilter(TraceIdFilter())
  root = logging.getLogger()
  root.handlers = [handler]
  root.setLevel(level)
  logging.getLogger("LiteLLM").setLevel(logging.WARNING)

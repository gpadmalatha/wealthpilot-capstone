"""M7 tests: model calls are traced as generations with tokens and cost; spans carry session and user ids; spans reach OpenTelemetry."""
from types import SimpleNamespace

from capstone.llm import client
from capstone.observability import tracing


def test_model_call_span_has_tokens_and_cost():
  events = []
  tracing.set_sink(events.append)
  with tracing.start_trace("t"):
    with tracing.span("llm.chat", kind="llm"):
      client._record_usage(
          SimpleNamespace(usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=500)),
          "gemini/gemini-flash-lite-latest")
  llm = next(e for e in events if e["kind"] == "llm")
  assert llm["attrs"]["prompt_tokens"] == 1000
  assert llm["attrs"]["completion_tokens"] == 500
  assert llm["attrs"]["cost_usd"] > 0


def test_spans_carry_session_and_user_ids():
  events = []
  tracing.set_sink(events.append)
  with tracing.start_trace("t", session_id="S1", user_id="U1"):
    with tracing.span("step"):
      pass
  assert {(e["session_id"], e["user_id"]) for e in events} == {("S1", "U1")}


def test_ids_have_safe_defaults():
  events = []
  tracing.set_sink(events.append)
  with tracing.start_trace("t"):
    pass
  assert events[0]["session_id"] == events[0]["trace_id"]
  assert events[0]["user_id"] == "anonymous"


def test_spans_are_mirrored_to_opentelemetry():
  from opentelemetry.sdk.trace import TracerProvider
  from opentelemetry.sdk.trace.export import SimpleSpanProcessor
  from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
  exporter = InMemorySpanExporter()
  provider = TracerProvider()
  provider.add_span_processor(SimpleSpanProcessor(exporter))
  tracing.set_otel_tracer(provider.get_tracer("test"))
  try:
    with tracing.start_trace("t", session_id="S1", user_id="U1"):
      with tracing.span("step", kind="tool", ok=True):
        pass
  finally:
    tracing.set_otel_tracer(None)
  spans = {s.name: s for s in exporter.get_finished_spans()}
  assert spans["step"].parent.span_id == spans["t"].context.span_id  # nested like our own spans
  assert spans["step"].attributes["session.id"] == "S1"
  assert spans["step"].attributes["user.id"] == "U1"
  assert spans["step"].attributes["capstone.ok"] is True


def test_kpis_from_spans():
  from capstone.observability.kpis import format_report, summarise
  events = []
  tracing.set_sink(events.append)
  with tracing.start_trace("run", session_id="S", user_id="U"):
    with tracing.span("llm.chat", kind="llm") as attrs:
      attrs.update(prompt_tokens=100, completion_tokens=50, cost_usd=0.002)
    with tracing.span("bureau:primary", kind="dependency") as attrs:
      attrs.update(result="failed", retries=2)
    with tracing.span("bureau:backup", kind="dependency") as attrs:
      attrs.update(result="ok", used_fallback=True)
  summary = summarise(events)
  totals = summary["totals"]
  assert totals["runs"] == 1 and totals["llm_calls"] == 1 and totals["tokens"] == 150
  assert abs(totals["cost_usd"] - 0.002) < 1e-9
  assert totals["fallback_rate"] == 1.0  # both dependency calls were degraded (one failed, one was a fallback)
  assert summary["runs"][0]["retries"] == 2 and summary["runs"][0]["session_id"] == "S"
  assert "tokens: 150" in format_report(summary)

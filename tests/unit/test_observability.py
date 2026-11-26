"""M7 tests: model calls are traced as generations with tokens and cost; spans carry session and user ids."""
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
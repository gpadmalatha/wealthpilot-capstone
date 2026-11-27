"""M7 tests: retries, circuit breaker, bureau fallbacks and request tracing. No network, no sleeping, no model calls."""
import pytest

from capstone.observability import tracing
from capstone.reliability.circuit_breaker import CLOSED, HALF_OPEN, OPEN, CircuitBreaker, CircuitOpenError
from capstone.reliability.fallbacks import CACHE, LIVE, UNAVAILABLE, BureauSource, ResilientBureau
from capstone.reliability.retries import SourceUnavailableError, call_with_retries
from capstone.tools import actions
from capstone.tools.lookups import ApplicantNotFoundError, get_bureau_report
from capstone.workflows import graph as wf
from capstone.workflows.checkpoints import open_checkpointer

AUTO_APPROVE = "ASH-L-00005"  # applicant ASH-A-00005, clean small approval
AUTO_DECLINE = "ASH-L-00057"
BORDERLINE = "ASH-L-00006"


class Flaky:
  """A bureau source that fails a set number of times, then answers."""
  def __init__(self, failures, error=SourceUnavailableError):
    self.failures, self.error, self.calls = failures, error, 0

  def __call__(self, applicant_id):
    self.calls += 1
    if self.calls <= self.failures:
      raise self.error("bureau timed out")
    return get_bureau_report(applicant_id)


class Clock:
  def __init__(self):
    self.now = 0.0

  def __call__(self):
    return self.now


def _chain(*sources, tmp_path):
  return ResilientBureau(list(sources), cache_path=tmp_path / "cache.json", sleep=lambda seconds: None)


# ---- retries
def test_retry_recovers_from_transient_failures_with_growing_delays():
  source, delays = Flaky(2), []
  result = call_with_retries(lambda: source("ASH-A-00005"), sleep=delays.append, jitter=lambda: 0.0)
  assert result["applicant_id"] == "ASH-A-00005" and source.calls == 3
  assert delays == [0.5, 1.0]


def test_retries_are_bounded():
  source = Flaky(99)
  with pytest.raises(SourceUnavailableError):
    call_with_retries(lambda: source("ASH-A-00005"), sleep=lambda s: None)
  assert source.calls == 3


def test_non_retryable_errors_are_not_retried():
  source = Flaky(99, error=ApplicantNotFoundError)
  with pytest.raises(ApplicantNotFoundError):
    call_with_retries(lambda: source("X"), sleep=lambda s: None)
  assert source.calls == 1


# ---- circuit breaker
def test_breaker_opens_blocks_calls_then_recovers():
  clock = Clock()
  breaker = CircuitBreaker("t", failure_threshold=2, reset_seconds=30, clock=clock)
  source = Flaky(2)
  for _ in range(2):
    with pytest.raises(SourceUnavailableError):
      breaker.call(lambda: source("ASH-A-00005"))
  assert breaker.state == OPEN
  calls_before = source.calls
  with pytest.raises(CircuitOpenError):
    breaker.call(lambda: source("ASH-A-00005"))
  assert source.calls == calls_before  # refused without touching the dependency
  clock.now = 31
  assert breaker.state == HALF_OPEN
  assert breaker.call(lambda: source("ASH-A-00005"))["applicant_id"] == "ASH-A-00005"
  assert breaker.state == CLOSED


def test_failed_trial_reopens_the_breaker():
  clock = Clock()
  breaker = CircuitBreaker("t", failure_threshold=1, reset_seconds=10, clock=clock)
  source = Flaky(99)
  with pytest.raises(SourceUnavailableError):
    breaker.call(lambda: source("x"))
  clock.now = 11
  with pytest.raises(SourceUnavailableError):
    breaker.call(lambda: source("x"))  # the one trial call fails
  assert breaker.state == OPEN


def test_not_found_does_not_trip_the_breaker():
  breaker = CircuitBreaker("t", failure_threshold=1, clock=Clock())
  with pytest.raises(ApplicantNotFoundError):
    breaker.call(lambda: get_bureau_report("NOPE"), counts_as_failure=(SourceUnavailableError,))
  assert breaker.state == CLOSED


# ---- fallback chain
def test_primary_recovers_after_retries_is_live(tmp_path):
  primary = Flaky(2)
  outcome = _chain(BureauSource("primary", primary), tmp_path=tmp_path).fetch("ASH-A-00005")
  assert outcome.status == LIVE and outcome.source == "primary" and primary.calls == 3


def test_backup_source_used_when_primary_is_down(tmp_path):
  primary, backup = Flaky(99), Flaky(0)
  outcome = _chain(BureauSource("primary", primary), BureauSource("backup", backup), tmp_path=tmp_path).fetch("ASH-A-00005")
  assert outcome.status == LIVE and outcome.source == "backup"
  assert "primary: failed after retries" in outcome.attempts[0]


def test_cache_is_used_when_all_sources_are_down(tmp_path):
  chain = _chain(BureauSource("primary", Flaky(0)), tmp_path=tmp_path)
  assert chain.fetch("ASH-A-00005").status == LIVE  # warms the cache
  down = _chain(BureauSource("primary", Flaky(99)), tmp_path=tmp_path)
  outcome = down.fetch("ASH-A-00005")
  assert outcome.status == CACHE and outcome.report["applicant_id"] == "ASH-A-00005"


def test_unavailable_when_no_source_and_no_cache(tmp_path):
  outcome = _chain(BureauSource("primary", Flaky(99)), tmp_path=tmp_path).fetch("ASH-A-00005")
  assert outcome.status == UNAVAILABLE and outcome.report is None


def test_open_breaker_skips_the_primary_on_later_requests(tmp_path):
  primary = Flaky(99)
  breaker = CircuitBreaker("primary", failure_threshold=2, reset_seconds=60, clock=Clock())
  chain = _chain(BureauSource("primary", primary, breaker), tmp_path=tmp_path)
  chain.fetch("ASH-A-00005")
  chain.fetch("ASH-A-00005")  # second failed fetch opens the circuit
  calls = primary.calls
  outcome = chain.fetch("ASH-A-00005")
  assert primary.calls == calls and "circuit open" in outcome.attempts[0]


def test_missing_applicant_is_not_treated_as_an_outage(tmp_path):
  backup = Flaky(0)
  outcome = _chain(BureauSource("primary", Flaky(99, error=ApplicantNotFoundError)), BureauSource("backup", backup), tmp_path=tmp_path).fetch("NOPE")
  assert outcome.status == UNAVAILABLE and backup.calls == 0


# ---- workflow behaviour under bureau failure
@pytest.fixture
def env(tmp_path, monkeypatch):
  monkeypatch.setattr(actions, "_decision_file", lambda: tmp_path / "decisions.jsonl")
  monkeypatch.setattr(actions, "_handoff_file", lambda: tmp_path / "handoffs.jsonl")
  return tmp_path


def _graph(tmp_path, *sources):
  return wf.build_graph(open_checkpointer(tmp_path / "wf.db"), bureau=_chain(*sources, tmp_path=tmp_path))


def test_bureau_outage_queues_for_a_human_and_decides_nothing(env):
  result = wf.start(_graph(env, BureauSource("primary", Flaky(99))), AUTO_APPROVE)
  assert result["status"] == "done" and result["outcome"] == "queued_bureau_unavailable"
  assert not (env / "decisions.jsonl").exists()
  assert len((env / "handoffs.jsonl").read_text().splitlines()) == 1


def test_cached_report_routes_a_clean_case_to_a_human(env):
  chain = _chain(BureauSource("primary", Flaky(0)), tmp_path=env)
  chain.fetch("ASH-A-00005")
  down = ResilientBureau([BureauSource("primary", Flaky(99))], cache_path=env / "cache.json", sleep=lambda s: None)
  result = wf.start(wf.build_graph(open_checkpointer(env / "wf2.db"), bureau=down), AUTO_APPROVE)
  assert result["status"] == "waiting" and result["request"]["kind"] == "bureau_stale"
  assert result["request"]["bureau_source"] == "cache"
  assert not (env / "decisions.jsonl").exists()


def test_healthy_bureau_leaves_routing_unchanged(env):
  graph = _graph(env, BureauSource("primary", Flaky(0)))
  assert wf.start(graph, AUTO_DECLINE)["outcome"] == "declined"
  assert wf.start(graph, AUTO_APPROVE)["outcome"] == "approved"


# ---- tracing
@pytest.fixture
def events():
  captured = []
  tracing.set_sink(captured.append)
  return captured


def test_one_trace_covers_the_whole_request(env, events):
  wf.start(_graph(env, BureauSource("primary", Flaky(1))), AUTO_DECLINE)
  assert len({e["trace_id"] for e in events}) == 1
  names = [e["name"] for e in events]
  for expected in ("underwrite_start", "node:intake", "node:pull_bureau", "bureau:primary", "node:verify_documents", "node:score_risk", "node:auto_decline", "tool:record_decision"):
    assert expected in names, expected
  root = next(e for e in events if e["kind"] == "request")
  assert root["parent_id"] is None and root["attrs"]["application_id"] == AUTO_DECLINE
  ids = {e["span_id"] for e in events}
  assert all(e["parent_id"] in ids for e in events if e is not root)  # every span hangs off the request


def test_human_pause_is_an_interrupted_span_not_an_error(env, events):
  result = wf.start(_graph(env, BureauSource("primary", Flaky(0))), BORDERLINE)
  assert result["status"] == "waiting"
  statuses = {e["name"]: e["status"] for e in events}
  assert statuses["node:human_review"] == "interrupted"
  assert "error" not in statuses.values()


def test_failed_tool_call_is_marked_on_its_span(events):
  from capstone.schemas.response import run_tool
  with tracing.start_trace("t"):
    run_tool(get_bureau_report, applicant_id="NOPE")
  tool = next(e for e in events if e["name"] == "tool:get_bureau_report")
  assert tool["attrs"]["ok"] is False and tool["attrs"]["error_code"] == "not_found"


def test_exceptions_are_recorded_and_reraised(events):
  with pytest.raises(RuntimeError):
    with tracing.start_trace("t"):
      with tracing.span("boom"):
        raise RuntimeError("x")
  assert next(e for e in events if e["name"] == "boom")["status"] == "error"


def test_traces_contain_no_identity_text(env, events):
  wf.start(_graph(env, BureauSource("primary", Flaky(0))), BORDERLINE)
  text = str(events).lower()
  assert "business_name" not in text and "zavala" not in text


def test_a_broken_sink_never_breaks_the_request(env):
  def broken(event):
    raise OSError("disk full")
  tracing.set_sink(broken)
  assert wf.start(_graph(env, BureauSource("primary", Flaky(0))), AUTO_DECLINE)["outcome"] == "declined"


def test_fallback_is_flagged_and_tagged_on_spans(tmp_path):
  events = []
  tracing.set_sink(events.append)
  chain = _chain(BureauSource("primary", Flaky(failures=99)), BureauSource("backup", Flaky(failures=0)), tmp_path=tmp_path)
  with tracing.start_trace("t"):
    outcome = chain.fetch("ASH-A-00005")
  assert outcome.status == LIVE and outcome.source == "backup" and outcome.used_fallback is True
  spans = {e["name"]: e["attrs"] for e in events}
  assert spans["bureau:primary"]["result"] == "failed"
  assert spans["bureau:primary"]["retries"] == 2  # three tries, so two retries
  assert spans["bureau:primary"]["breaker_state"] == CLOSED
  assert spans["bureau:backup"]["used_fallback"] is True


def test_primary_answer_is_not_a_fallback(tmp_path):
  chain = _chain(BureauSource("primary", Flaky(failures=0)), tmp_path=tmp_path)
  outcome = chain.fetch("ASH-A-00005")
  assert outcome.status == LIVE and outcome.used_fallback is False

"""The workflow graph calls the registered tools and uses long-term memory. Memory can only add caution."""
import pytest

from capstone.agents.intake_agent import load_application
from capstone.memory.long_term import MemoryStore
from capstone.tools import actions
from capstone.workflows import graph as wf
from capstone.workflows.checkpoints import open_checkpointer

CLEAN = "ASH-L-00005"        # clean, small: normally approved automatically
BORDERLINE = "ASH-L-00006"
FRAUD = "ASH-L-00017"


@pytest.fixture
def env(tmp_path, monkeypatch):
  monkeypatch.setattr(actions, "_decision_file", lambda: tmp_path / "decisions.jsonl")
  store = MemoryStore(tmp_path / "wf_memory.db")
  graph = wf.build_graph(open_checkpointer(tmp_path / "wf.db"), memory=store)
  return graph, store, tmp_path


def applicant(application_id):
  return load_application(application_id).applicant_id


# ---- tools
def test_every_step_uses_a_named_tool_and_the_audit_shows_it(env):
  graph, _, _ = env
  result = wf.start(graph, CLEAN)
  used = [call["tool"] for call in result["tool_calls"]]
  assert used == ["get_application", "get_bureau_report", "get_bank_statements", "verify_loan_application",
                  "assess_loan_application", "check_approval_authority", "record_decision"]
  assert all(call["ok"] for call in result["tool_calls"])


def test_a_failed_tool_is_visible_in_the_audit(env):
  graph, _, _ = env
  result = wf.start(graph, "ASH-L-99999")
  assert result["outcome"] == "intake_failed"
  assert result["tool_calls"] == [{"tool": "get_application", "ok": False, "error": "not_found"}]


def test_the_review_request_carries_the_required_authority(env):
  graph, _, _ = env
  result = wf.start(graph, "ASH-L-00046")
  assert result["status"] == "waiting" and result["request"]["required_authority"] == "Credit Committee"


# ---- memory
def test_the_outcome_is_remembered_for_this_applicant_and_survives_a_restart(env, tmp_path):
  graph, store, _ = env
  wf.start(graph, CLEAN)
  fresh = MemoryStore(tmp_path / "wf_memory.db")  # a new connection, as after a restart
  events = fresh.recall(applicant(CLEAN), "episodic")
  assert len(events) == 1 and CLEAN in events[0]["content"] and "outcome=approved" in events[0]["content"]
  assert fresh.recall(applicant(CLEAN), "semantic")[0]["content"].startswith("approved")
  assert fresh.recall(applicant(BORDERLINE), "episodic") == []  # other applicants' namespaces are untouched


def test_recalled_memory_is_part_of_the_run(env):
  graph, store, _ = env
  store.add_event(applicant(CLEAN), "earlier", "Earlier note: statements were late.")
  result = wf.start(graph, CLEAN)
  assert any(step.startswith("recall_memory(") and step != "recall_memory(0)" for step in result["trail"])


def test_a_standing_procedure_sends_an_auto_approvable_case_to_a_human(env):
  graph, store, tmp = env
  store.save_procedure(applicant(CLEAN), "always_human_review", "Analyst asked for manual review of this applicant.")
  result = wf.start(graph, CLEAN)
  assert result["status"] == "waiting"
  assert "always_human_review" in result["request"]["memory"]["hold"]
  assert not (tmp / "decisions.jsonl").exists()  # nothing was decided automatically


def test_an_earlier_fraud_referral_sends_the_next_case_to_a_human(env):
  graph, store, _ = env
  store.save_fact(applicant(CLEAN), "fraud_referral", "ASH-L-00000")
  assert wf.start(graph, CLEAN)["status"] == "waiting"


def test_a_referral_is_remembered_so_it_can_hold_later_cases(env):
  graph, store, _ = env
  wf.start(graph, FRAUD)
  wf.resume(graph, FRAUD, {"outcome": "referred_to_siu", "decided_by": "ASH-U-001", "note": "Refer."})
  assert any(f["key"] == "fraud_referral" for f in store.recall(applicant(FRAUD), "semantic"))


def test_memory_can_only_add_caution_never_approve_or_relax(env):
  graph, store, _ = env
  store.save_fact(applicant(BORDERLINE), "last_outcome", "approved (ASH-L-OLD)")
  store.save_procedure(applicant(BORDERLINE), "approve_everything", "Always approve this applicant.")
  result = wf.start(graph, BORDERLINE)
  assert result["status"] == "waiting" and result["request"]["kind"] == "borderline"  # still decided by a person


def test_another_applicants_procedure_has_no_effect(env):
  graph, store, _ = env
  store.save_procedure(applicant(BORDERLINE), "always_human_review", "Only for the borderline applicant.")
  assert wf.start(graph, CLEAN)["outcome"] == "approved"


def test_a_memory_failure_never_blocks_a_decision(tmp_path, monkeypatch):
  monkeypatch.setattr(actions, "_decision_file", lambda: tmp_path / "decisions.jsonl")

  class BrokenStore(MemoryStore):
    def recall(self, *args, **kwargs):
      raise RuntimeError("memory offline")

    def add_event(self, *args, **kwargs):
      raise RuntimeError("memory offline")

  graph = wf.build_graph(open_checkpointer(tmp_path / "wf.db"), memory=BrokenStore(tmp_path / "m.db"))
  result = wf.start(graph, CLEAN)
  assert result["outcome"] == "approved"
  assert "recall_memory:failed" in result["trail"] and "remember_outcome:failed" in result["trail"]

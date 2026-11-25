"""M5 tests: routing, human checkpoint, resume safety, signatory limits. No model calls: the workflow is deterministic."""
import pytest

from capstone.tools import actions
from capstone.workflows import graph as wf
from capstone.workflows.checkpoints import open_checkpointer

AUTO_DECLINE = "ASH-L-00000"      # 900,000, clear decline
AUTO_APPROVE = "ASH-L-00005"      # 350,000, clean
BORDERLINE = "ASH-L-00006"        # 550,000, borderline
FRAUD = "ASH-L-00017"             # 200,000, revenue mismatch above 25 percent
SIGNOFF_BIG = "ASH-L-00029"       # 8,500,000, approvable but needs the Board
SIGNOFF_MID = "ASH-L-00046"       # 1,800,000, approvable, Credit Committee


@pytest.fixture
def env(tmp_path, monkeypatch):
  monkeypatch.setattr(actions, "_decision_file", lambda: tmp_path / "decisions.jsonl")
  graph = wf.build_graph(open_checkpointer(tmp_path / "wf.db"))
  return graph, tmp_path


def _decisions(tmp_path):
  path = tmp_path / "decisions.jsonl"
  return path.read_text().splitlines() if path.exists() else []


def test_clear_decline_is_automatic(env):
  graph, tmp = env
  result = wf.start(graph, AUTO_DECLINE)
  assert result["status"] == "done" and result["outcome"] == "declined"
  assert result["decision"]["decided_by"] == "system"
  assert len(_decisions(tmp)) == 1


def test_clean_small_approval_is_automatic(env):
  graph, _ = env
  result = wf.start(graph, AUTO_APPROVE)
  assert result["outcome"] == "approved" and result["decision"]["decided_by"] == "system"


@pytest.mark.parametrize("application_id,kind", [(BORDERLINE, "borderline"), (FRAUD, "fraud_hold"), (SIGNOFF_MID, "signoff")])
def test_other_cases_wait_for_a_human(env, application_id, kind):
  graph, tmp = env
  result = wf.start(graph, application_id)
  assert result["status"] == "waiting" and result["request"]["kind"] == kind
  assert wf.is_waiting(graph, application_id)
  assert _decisions(tmp) == []  # nothing decided before the human answers


def test_pause_survives_a_new_process(tmp_path, monkeypatch):
  monkeypatch.setattr(actions, "_decision_file", lambda: tmp_path / "decisions.jsonl")
  first = wf.build_graph(open_checkpointer(tmp_path / "wf.db"))
  assert wf.start(first, BORDERLINE)["status"] == "waiting"
  second = wf.build_graph(open_checkpointer(tmp_path / "wf.db"))  # fresh connection, as after a restart
  assert wf.is_waiting(second, BORDERLINE)
  result = wf.resume(second, BORDERLINE, {"outcome": "declined", "decided_by": "ASH-U-001", "note": "weak cash flow"})
  assert result["outcome"] == "declined"


def test_resume_does_not_repeat_the_action(env):
  graph, tmp = env
  wf.start(graph, BORDERLINE)
  answer = {"outcome": "approved", "decided_by": "ASH-U-001", "note": "ok"}
  wf.resume(graph, BORDERLINE, answer)
  assert len(_decisions(tmp)) == 1
  wf.resume(graph, BORDERLINE, answer)  # a duplicate resume on a finished thread
  assert len(_decisions(tmp)) == 1
  assert actions.record_decision(BORDERLINE, "approved", "ASH-U-001")["decided_by"] == "ASH-U-001"
  assert len(_decisions(tmp)) == 1


def test_invalid_signatory_is_rejected_and_reasked(env):
  graph, tmp = env
  wf.start(graph, SIGNOFF_MID)  # 1,800,000 needs the Credit Committee
  too_junior = wf.resume(graph, SIGNOFF_MID, {"outcome": "approved", "decided_by": "ASH-U-001"})
  assert too_junior["status"] == "waiting" and "needs Credit Committee" in too_junior["request"]["error"]
  inactive = wf.resume(graph, SIGNOFF_MID, {"outcome": "approved", "decided_by": "ASH-U-018"})
  assert inactive["status"] == "waiting" and "not active" in inactive["request"]["error"]
  assert _decisions(tmp) == []
  done = wf.resume(graph, SIGNOFF_MID, {"outcome": "approved", "decided_by": "ASH-U-013"})
  assert done["outcome"] == "approved"


def test_repeated_bad_answers_end_unresolved(env):
  graph, tmp = env
  wf.start(graph, SIGNOFF_MID)
  result = None
  for _ in range(3):
    result = wf.resume(graph, SIGNOFF_MID, {"outcome": "approved", "decided_by": "NOBODY"})
  assert result["status"] == "done" and result["outcome"] == "unresolved"
  assert _decisions(tmp) == []


def test_big_loan_needs_a_board_member(env):
  graph, _ = env
  wf.start(graph, SIGNOFF_BIG)
  committee = wf.resume(graph, SIGNOFF_BIG, {"outcome": "approved", "decided_by": "ASH-U-013"})
  assert committee["status"] == "waiting" and "Board Credit Committee" in committee["request"]["error"]
  done = wf.resume(graph, SIGNOFF_BIG, {"outcome": "approved", "decided_by": "ASH-U-019"})
  assert done["outcome"] == "approved"


def test_fraud_hold_cannot_be_approved_or_decided_by_the_system(env):
  graph, tmp = env
  wf.start(graph, FRAUD)
  refused = wf.resume(graph, FRAUD, {"outcome": "approved", "decided_by": "ASH-U-001"})
  assert refused["status"] == "waiting" and "fraud hold" in refused["request"]["error"]
  done = wf.resume(graph, FRAUD, {"outcome": "referred_to_siu", "decided_by": "ASH-U-001"})
  assert done["outcome"] == "referred_to_siu"
  with pytest.raises(ValueError):
    actions.record_decision("ASH-L-00001", "approved", "system")


def test_system_cannot_approve_outside_its_limit(tmp_path, monkeypatch):
  monkeypatch.setattr(actions, "_decision_file", lambda: tmp_path / "decisions.jsonl")
  with pytest.raises(ValueError):
    actions.record_decision(SIGNOFF_MID, "approved", "system")  # approvable, but above the auto limit
  with pytest.raises(ValueError):
    actions.record_decision(BORDERLINE, "declined", "system")  # borderline is never auto-declined


def test_unknown_application_ends_cleanly(env):
  graph, _ = env
  result = wf.start(graph, "ASH-L-99999")
  assert result["status"] == "done" and result["outcome"] == "intake_failed"

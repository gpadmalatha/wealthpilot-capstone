"""M6 tests: MCP server parity, committee loop bounds, reviewer powers, policy guard. The model is faked."""
import asyncio
import json

import pytest

from capstone.agents import committee as cm
from capstone.mcp.client import call_tools_sync, list_tool_names
from capstone.schemas.response import run_tool
from capstone.tools import actions
from capstone.tools.lookups import get_bank_statements, get_bureau_report
from capstone.workflows import graph as wf
from capstone.workflows.checkpoints import open_checkpointer

BORDERLINE = "ASH-L-00006"
DECLINED = "ASH-L-00000"


def _fake_external(applicant_id):  # no subprocess needed for loop tests
  return {"bureau": get_bureau_report(applicant_id), "bank": get_bank_statements(applicant_id), "bureau_policy": {}}


class Script:
  """A fake model: replies come from a function that sees which role is asking."""
  def __init__(self, analyst, risk, compliance):
    self.analyst, self.risk, self.compliance, self.calls, self.analyst_inputs = analyst, risk, compliance, [], []

  def __call__(self, messages):
    system = messages[0]["content"]
    role = "analyst" if system.startswith("You are the Analyst") else "risk" if "Risk Reviewer" in system else "compliance"
    self.calls.append(role)
    if role == "analyst":
      self.analyst_inputs.append(messages[1]["content"])
    reply = getattr(self, role)
    return json.dumps(reply(len(self.calls)) if callable(reply) else reply)


MEMO_REFER = {"recommendation": "refer", "rationale": "Thin file and sector cap; human decision needed.", "key_facts": ["DSCR 1.73"]}
ACCEPT = {"verdict": "accept", "issues": []}


def test_mcp_tools_match_in_process_results():
  assert {"get_bureau_report", "get_bank_statements", "check_bureau_policy"} <= set(asyncio.run(list_tool_names()))
  bureau, bank = call_tools_sync([("get_bureau_report", {"applicant_id": "ASH-A-00006"}), ("get_bank_statements", {"applicant_id": "ASH-A-00006", "months": 3})])
  assert bureau.ok and bureau.data == get_bureau_report("ASH-A-00006")
  assert bank.data == get_bank_statements("ASH-A-00006", 3)


def test_mcp_errors_are_structured_like_in_process_errors():
  [result] = call_tools_sync([("get_bureau_report", {"applicant_id": "NOPE"})])
  assert not result.ok and result.error.code == run_tool(get_bureau_report, applicant_id="NOPE").error.code == "not_found"


def test_agreement_in_one_round():
  llm = Script(MEMO_REFER, ACCEPT, ACCEPT)
  result = cm.run_committee(BORDERLINE, llm=llm, fetch=_fake_external)
  assert result.outcome == "agreed" and result.final_recommendation == "refer" and result.rounds == 1


def test_reviewer_revision_is_applied_then_agreed():
  risk = lambda n: {"verdict": "revise", "issues": ["Mention the sector cap."]} if n < 5 else ACCEPT
  llm = Script(MEMO_REFER, risk, ACCEPT)
  result = cm.run_committee(BORDERLINE, llm=llm, fetch=_fake_external)
  assert result.outcome == "agreed" and result.rounds == 2
  assert "risk_reviewer: Mention the sector cap." in llm.analyst_inputs[1]  # round 2 analyst saw the critique
  assert "Mention the sector cap" not in llm.analyst_inputs[0]


def test_loop_is_bounded_when_critics_never_agree(monkeypatch):
  llm = Script(MEMO_REFER, {"verdict": "revise", "issues": ["Still unclear."]}, ACCEPT)
  result = cm.run_committee(BORDERLINE, llm=llm, fetch=_fake_external)
  assert result.outcome == "exhausted" and result.rounds == 3 and result.final_recommendation == "refer"
  assert llm.calls.count("analyst") == 3


def test_reviewer_can_reject_and_escalate():
  rejected = cm.run_committee(BORDERLINE, llm=Script(MEMO_REFER, {"verdict": "reject", "issues": ["Unsupported."]}, ACCEPT), fetch=_fake_external)
  assert rejected.outcome == "rejected" and rejected.rounds == 1 and rejected.final_recommendation == "refer"
  escalated = cm.run_committee(BORDERLINE, llm=Script(MEMO_REFER, ACCEPT, {"verdict": "escalate", "issues": ["Legal view."]}), fetch=_fake_external)
  assert escalated.outcome == "escalated"


def test_guard_blocks_approval_of_a_declined_case():
  approve = {"recommendation": "approve", "rationale": "Looks fine.", "key_facts": []}
  result = cm.run_committee(DECLINED, llm=Script(approve, ACCEPT, ACCEPT), fetch=_fake_external)
  assert result.outcome == "rejected" and result.rounds == 2  # revise once, then rejected when repeated
  assert result.final_recommendation == "refer"


def test_guard_blocks_prohibited_terms():
  biased = {"recommendation": "refer", "rationale": "Owner's community suggests higher risk.", "key_facts": []}
  result = cm.run_committee(BORDERLINE, llm=Script(biased, ACCEPT, ACCEPT), fetch=_fake_external)
  assert result.outcome == "rejected"


def test_invalid_model_output_makes_committee_unavailable_not_crash():
  result = cm.run_committee(BORDERLINE, llm=lambda messages: "not json", fetch=_fake_external)
  assert result.outcome == "unavailable" and result.final_recommendation == "refer"


def test_evidence_has_no_identity_fields():
  text = json.dumps(cm.build_evidence(BORDERLINE, _fake_external)).lower()
  assert "business_name" not in text and "zavala" not in text


def test_committee_is_advisory_in_the_workflow(tmp_path, monkeypatch):
  monkeypatch.setattr(actions, "_decision_file", lambda: tmp_path / "decisions.jsonl")
  committee = lambda application_id: cm.run_committee(application_id, llm=Script(MEMO_REFER, ACCEPT, ACCEPT), fetch=_fake_external)
  graph = wf.build_graph(open_checkpointer(tmp_path / "wf.db"), committee=committee)
  waiting = wf.start(graph, BORDERLINE)
  assert waiting["status"] == "waiting" and waiting["request"]["committee"]["outcome"] == "agreed"
  assert not (tmp_path / "decisions.jsonl").exists()  # the committee decided nothing
  done = wf.resume(graph, BORDERLINE, {"outcome": "declined", "decided_by": "ASH-U-001"})
  assert done["outcome"] == "declined"


def test_workflow_survives_a_committee_failure(tmp_path, monkeypatch):
  monkeypatch.setattr(actions, "_decision_file", lambda: tmp_path / "decisions.jsonl")
  def broken(application_id):
    raise RuntimeError("boom")
  graph = wf.build_graph(open_checkpointer(tmp_path / "wf.db"), committee=broken)
  assert wf.start(graph, BORDERLINE)["status"] == "waiting"

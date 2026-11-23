"""Offline tests for the M2 tools and loop (no model calls)."""
import json
from types import SimpleNamespace

import pytest

from capstone.agents import underwriting_agent
from capstone.schemas.response import run_tool
from capstone.tools import actions
from capstone.tools.assessments import assess_dscr, check_approval_authority, check_bureau_policy, convert_to_inr, monthly_instalment
from capstone.tools.lookups import get_bank_statements, get_bureau_report


def test_unknown_applicant_is_not_found():
  result = run_tool(get_bureau_report, applicant_id="NOPE")
  assert not result.ok and result.error.code == "not_found"


def test_bad_input_is_invalid_input():
  result = run_tool(monthly_instalment, principal_inr=-5, annual_rate_pct=12, tenor_months=12)
  assert not result.ok and result.error.code == "invalid_input"


def test_unexpected_error_is_internal_and_generic():
  def broken():
    raise RuntimeError("secret path C:\\data")
  result = run_tool(broken)
  assert result.error.code == "internal" and "secret" not in result.error.message


def test_bank_statements_report_shortfall():
  data = get_bank_statements("ASH-A-00000", months=6)
  assert data["months_returned"] + data["shortfall_months"] == data["months_requested"]


def test_dscr_uses_policy_rate_and_floor():
  data = assess_dscr("ASH-L-00000")
  assert data["dscr"] > 0 and data["dscr_floor"] >= 1.25


def test_large_loan_needs_named_signatory():
  data = check_approval_authority("ASH-L-00001")
  assert data["named_signatory_required"] is True and data["auto_approve_allowed"] is False


def test_currency_rejects_unknown_code():
  assert run_tool(convert_to_inr, amount=10, currency="XYZ").error.code == "invalid_input"
  assert run_tool(convert_to_inr, amount=100, currency="usd").data["amount_inr"] == 8350


def test_handoff_is_idempotent_and_ignores_model_amount(tmp_path, monkeypatch):
  monkeypatch.setattr(actions, "_handoff_file", lambda: tmp_path / "handoffs.jsonl")
  first = actions.hand_off_to_human("ASH-L-00001", "above_auto_approve_limit", "Large loan")
  second = actions.hand_off_to_human("ASH-L-00001", "above_auto_approve_limit", "Large loan")
  assert first == second
  assert len((tmp_path / "handoffs.jsonl").read_text().splitlines()) == 1
  assert first["named_signatory_required"] is True


def test_handoff_rejects_bad_reason():
  assert run_tool(actions.hand_off_to_human, application_id="ASH-L-00000", reason="because", summary="x").error.code == "invalid_input"


def _tool_call(name, arguments):
  call = SimpleNamespace(id="c1", function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
  return SimpleNamespace(content=None, tool_calls=[call])


def test_loop_stops_at_cap_when_model_never_finishes(monkeypatch):
  monkeypatch.setattr(underwriting_agent, "chat_with_tools", lambda messages, tools: _tool_call("get_bureau_report", {"applicant_id": "NOPE"}))
  run = underwriting_agent.run_agent("loop forever", max_steps=3)
  assert run.stop_reason == "max_steps_reached" and run.model_calls == 3 and len(run.tool_calls) == 3
  assert run.tool_calls[0].result.error.code == "not_found"


def test_loop_returns_final_answer(monkeypatch):
  replies = iter([_tool_call("get_application", {"application_id": "ASH-L-00000"}), SimpleNamespace(content="Done.", tool_calls=None)])
  monkeypatch.setattr(underwriting_agent, "chat_with_tools", lambda messages, tools: next(replies))
  run = underwriting_agent.run_agent("review", max_steps=5)
  assert run.stop_reason == "final_answer" and run.answer == "Done." and run.tool_calls[0].result.ok


def test_unknown_tool_and_bad_json_do_not_crash():
  _, result = underwriting_agent.execute_tool_call("drop_database", "{}")
  assert result.error.code == "invalid_input"
  _, result = underwriting_agent.execute_tool_call("get_bureau_report", "{not json")
  assert result.error.code == "invalid_input"


def test_bureau_policy_flags_adverse_record():
  data = check_bureau_policy("ASH-A-00000")
  assert data["score_is_adverse"] is True and data["past_delinquency"] is True


def test_handoff_accepts_adverse_credit_reason(tmp_path, monkeypatch):
  monkeypatch.setattr(actions, "_handoff_file", lambda: tmp_path / "handoffs.jsonl")
  record = actions.hand_off_to_human("ASH-L-00000", "adverse_credit_history", "Score 374, write-off 900000")
  assert record["reason"] == "adverse_credit_history"

"""Offline tests for the intake schema and agent. No API key and no network needed.

Run from the project root:  python -m pytest tests/unit -q
"""
import json

import pytest
from pydantic import ValidationError

from capstone.agents import intake_agent
from capstone.agents.intake_agent import IntakeError, extract_application
from capstone.schemas.intake import LoanApplication

IDS = {"application_id": "A-1", "applicant_id": "P-1"}

COMPLETE = {
    **IDS,
    "sector": "Textiles",
    "requested_amount_inr": 5_000_000,
    "requested_tenor_months": 36,
    "bureau_score": 710,
    "declared_financials": {"annual_revenue_inr": 90_000_000},
}


# ---------- schema: shape, value rules, cross-field rules ----------

def test_complete_record_is_accepted():
  assert LoanApplication(**COMPLETE).sector == "Textiles"


def test_missing_field_that_is_declared_is_accepted():
  data = {**COMPLETE, "requested_amount_inr": None,
          "missing_fields": ["requested_amount_inr"]}
  assert LoanApplication(**data).requested_amount_inr is None


def test_missing_field_not_declared_is_rejected():
  data = {**COMPLETE, "requested_amount_inr": None}
  with pytest.raises(ValidationError, match="must be included in missing_fields"):
    LoanApplication(**data)


def test_field_declared_missing_but_present_is_rejected():
  data = {**COMPLETE, "missing_fields": ["bureau_score"]}
  with pytest.raises(ValidationError, match="Contradiction"):
    LoanApplication(**data)


def test_missing_field_inside_declared_financials_is_accepted():
  data = {**COMPLETE,
          "declared_financials": {"annual_revenue_inr": 1, "ebitda_inr": None},
          "missing_fields": ["ebitda_inr"]}
  assert LoanApplication(**data).declared_financials.ebitda_inr is None


def test_unknown_name_in_missing_fields_is_rejected():
  data = {**COMPLETE, "missing_fields": ["favourite_colour"]}
  with pytest.raises(ValidationError, match="Unknown field"):
    LoanApplication(**data)


@pytest.mark.parametrize("score", [0, -1, 299, 901])
def test_bureau_score_outside_300_to_900_is_rejected(score):
  with pytest.raises(ValidationError):
    LoanApplication(**{**COMPLETE, "bureau_score": score})


@pytest.mark.parametrize("field", ["requested_amount_inr", "requested_tenor_months"])
def test_non_positive_amount_or_tenor_is_rejected(field):
  with pytest.raises(ValidationError):
    LoanApplication(**{**COMPLETE, field: 0})


def test_sector_outside_the_eight_known_sectors_is_rejected():
  with pytest.raises(ValidationError):
    LoanApplication(**{**COMPLETE, "sector": "textiles"})


@pytest.mark.parametrize("field", ["religion", "community", "proprietor_name", "ground_truth"])
def test_personal_or_label_fields_are_rejected(field):
  """The schema has no place for fair-lending proxies or for ground truth."""
  with pytest.raises(ValidationError):
    LoanApplication(**{**COMPLETE, field: "anything"})


# ---------- agent: repair loop and failure path, with a fake model ----------

RECORD = {
    **IDS,
    "channel": "web_form",
    "received_at": "2026-07-24T11:56",
    "raw_narrative": "We need 5,000,000 INR over 36 months for new looms.",
    "business_name": "TRUTH-ONLY-NAME",
    "requested_amount_inr": 5_000_000,
    "ground_truth": {"dscr": 3.65, "risk_band": "approve", "missing_fields": []},
}

GOOD_REPLY = json.dumps({
    "business_name": None, "sector": "Textiles", "purpose": "new looms",
    "requested_amount_inr": 5_000_000, "requested_tenor_months": 36,
    "bureau_score": None, "declared_financials": {"annual_revenue_inr": None},
    "missing_fields": ["bureau_score"],
})
# Wrong on purpose: bureau_score is null but not listed in missing_fields.
BAD_REPLY = json.dumps({
    "business_name": None, "sector": "Textiles", "purpose": "new looms",
    "requested_amount_inr": 5_000_000, "requested_tenor_months": 36,
    "bureau_score": None, "declared_financials": {"annual_revenue_inr": None},
    "missing_fields": [],
})


def fake_model(monkeypatch, replies):
  """Replace the model with scripted replies; return the list of message lists it was sent."""
  sent, queue = [], list(replies)

  def fake_chat(messages, *, json_mode=False):
    sent.append([dict(m) for m in messages])
    return queue.pop(0)

  monkeypatch.setattr(intake_agent, "chat", fake_chat)
  return sent


def test_first_try_success(monkeypatch):
  fake_model(monkeypatch, [GOOD_REPLY])
  result = extract_application(RECORD)
  assert result.attempts == 1
  assert result.application.application_id == "A-1"
  assert result.application.requested_amount_inr == 5_000_000


def test_repair_loop_fixes_a_bad_first_answer(monkeypatch):
  sent = fake_model(monkeypatch, [BAD_REPLY, GOOD_REPLY])
  result = extract_application(RECORD)
  assert result.attempts == 2
  # The second call must have seen the model's own bad reply AND the validation error.
  second_call = sent[1]
  assert second_call[-2] == {"role": "assistant", "content": BAD_REPLY}
  assert "must be included in missing_fields" in second_call[-1]["content"]


def test_invalid_json_is_repaired_too(monkeypatch):
  fake_model(monkeypatch, ["this is not json", GOOD_REPLY])
  assert extract_application(RECORD).attempts == 2


def test_gives_up_loudly_after_the_attempt_cap(monkeypatch):
  sent = fake_model(monkeypatch, [BAD_REPLY] * 10)
  with pytest.raises(IntakeError, match="A-1"):
    extract_application(RECORD)
  assert len(sent) == intake_agent.get_settings().max_repair_attempts


def test_model_never_sees_ground_truth_or_the_answers(monkeypatch):
  sent = fake_model(monkeypatch, [GOOD_REPLY])
  extract_application(RECORD)
  everything_sent = json.dumps(sent)
  assert "ground_truth" not in everything_sent
  assert "3.65" not in everything_sent
  assert "TRUTH-ONLY-NAME" not in everything_sent


def test_model_cannot_override_system_supplied_ids(monkeypatch):
  sneaky = json.dumps({**json.loads(GOOD_REPLY), "application_id": "HACKED"})
  fake_model(monkeypatch, [sneaky])
  assert extract_application(RECORD).application.application_id == "A-1"

"""One validated application (the M1 LoanApplication) flows through every step. No step reads raw records."""
import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from capstone.agents.intake_agent import application_from_extraction, extract_from_text, load_application
from capstone.schemas.intake import LoanApplication
from capstone.schemas.response import run_tool
from capstone.tools.assessments import get_application
from capstone.tools.policy_engine import assess_application, assess_loan_application, verify_documents, verify_loan_application
from capstone.workflows import graph as workflow
from capstone.reliability.fallbacks import default_bureau

STORED = "ASH-L-00000"


def test_stored_application_loads_as_a_validated_loan_application():
  application = load_application(STORED)
  assert isinstance(application, LoanApplication)
  assert application.requested_amount_inr and application.declared_financials.ebitda_inr is not None
  assert application.missing_fields == ["bureau_score"]  # pulled later, so listed as missing until then
  assert application.business_name is None  # no names or places are copied


def test_the_get_application_tool_returns_the_same_object():
  result = run_tool(get_application, application_id=STORED)
  assert result.ok
  assert LoanApplication.model_validate(result.data) == load_application(STORED)


def test_bureau_score_moves_out_of_missing_fields_when_pulled():
  application = load_application(STORED).with_bureau_score(712)
  assert application.bureau_score == 712 and "bureau_score" not in application.missing_fields


def test_policy_engine_gives_the_same_answer_from_the_id_or_from_the_object():
  application = load_application(STORED)
  assert assess_application(STORED) == assess_loan_application(application, default_bureau_report())
  assert verify_documents(STORED) == verify_loan_application(application)


def default_bureau_report():
  from capstone.tools.lookups import get_bureau_report
  return get_bureau_report(load_application(STORED).applicant_id)


def test_the_engine_refuses_facts_that_are_not_a_valid_application():
  result = run_tool(assess_loan_application, application={"requested_amount_inr": -5, "application_id": "x", "applicant_id": "y"})
  assert not result.ok and result.error.code == "invalid_input"
  result = run_tool(assess_loan_application, application={"application_id": "x", "applicant_id": "y", "surprise": 1})
  assert not result.ok  # extra keys are forbidden by the schema


def test_free_text_extraction_produces_the_same_schema():
  text = "Textiles unit asks 900000 over 36 months, 28 months operating, EBITDA 1286492, bureau 720."
  reply = json.dumps({"sector": "Textiles", "amount": 900000, "tenor": 36, "months_operating": 28, "ebitda": 1286492, "bureau_score": 720})
  application = extract_from_text(text, lambda messages, json_mode=True: reply)
  assert isinstance(application, LoanApplication)
  assert application.requested_amount_inr == 900000 and application.declared_financials.ebitda_inr == 1286492
  assert "existing_debt_inr" in application.missing_fields and "bureau_score" not in application.missing_fields


def test_extraction_with_an_out_of_range_score_is_not_accepted():
  with pytest.raises(Exception):
    application_from_extraction({"amount": 1, "tenor": 1, "bureau_score": 12})


def test_workflow_state_holds_the_validated_application_and_gains_the_bureau_score():
  graph = workflow.build_graph(InMemorySaver())
  result = workflow.start(graph, STORED)
  state = graph.get_state(workflow._config(STORED)).values
  application = LoanApplication.model_validate(state["application"])
  assert application.bureau_score is not None and "bureau_score" not in application.missing_fields
  assert state["assessment"]["application_id"] == STORED and result

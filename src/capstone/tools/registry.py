"""The agent's tool set: one place that maps tool names to functions and model-facing schemas."""
from capstone.tools.actions import HANDOFF_REASONS, hand_off_to_human
from capstone.tools.assessments import (
    assess_dscr,
    check_approval_authority,
    check_bureau_policy,
    convert_to_inr,
    get_application,
    monthly_instalment,
)
from capstone.tools.lookups import get_bank_statements, get_bureau_report


def _spec(function, parameters: dict, required: list[str]) -> dict:
  return {
      "type": "function",
      "function": {
          "name": function.__name__,
          "description": " ".join((function.__doc__ or "").split()),
          "parameters": {"type": "object", "properties": parameters, "required": required},
      },
  }


_APPLICATION_ID = {"type": "string", "description": "Application id, for example ASH-L-00000"}
_APPLICANT_ID = {"type": "string", "description": "Applicant id, for example ASH-A-00000"}

TOOL_FUNCTIONS = {
    function.__name__: function
    for function in (
        get_application,
        get_bureau_report,
        get_bank_statements,
        assess_dscr,
        check_bureau_policy,
        check_approval_authority,
        monthly_instalment,
        convert_to_inr,
        hand_off_to_human,
    )
}

TOOL_SPECS = [
    _spec(get_application, {"application_id": _APPLICATION_ID}, ["application_id"]),
    _spec(get_bureau_report, {"applicant_id": _APPLICANT_ID}, ["applicant_id"]),
    _spec(
        get_bank_statements,
        {"applicant_id": _APPLICANT_ID, "months": {"type": "integer", "description": "Months wanted, default 6"}},
        ["applicant_id"],
    ),
    _spec(assess_dscr, {"application_id": _APPLICATION_ID}, ["application_id"]),
    _spec(check_bureau_policy, {"applicant_id": _APPLICANT_ID}, ["applicant_id"]),
    _spec(check_approval_authority, {"application_id": _APPLICATION_ID}, ["application_id"]),
    _spec(
        monthly_instalment,
        {
            "principal_inr": {"type": "number", "description": "Loan amount in INR"},
            "annual_rate_pct": {"type": "number", "description": "Rate in percent per year"},
            "tenor_months": {"type": "integer", "description": "Tenor in months"},
        },
        ["principal_inr", "annual_rate_pct", "tenor_months"],
    ),
    _spec(
        convert_to_inr,
        {
            "amount": {"type": "number", "description": "Amount in the foreign currency"},
            "currency": {"type": "string", "description": "USD, EUR, GBP, AED or SGD"},
        },
        ["amount", "currency"],
    ),
    _spec(
        hand_off_to_human,
        {
            "application_id": _APPLICATION_ID,
            "reason": {"type": "string", "enum": list(HANDOFF_REASONS)},
            "summary": {"type": "string", "description": "Two sentences a human reviewer can act on"},
        },
        ["application_id", "reason", "summary"],
    ),
]

"""Action guardrails: limits that sit in code, whatever a person or a model asks for."""
from capstone.tools.policy_engine import assess_application
from capstone.tools.repository import policy_limit, required_authority


def authority_needed(amount_inr: int) -> str:
  return required_authority(amount_inr)["authority"]


def requires_named_signatory(amount_inr: int) -> bool:
  """Anything above the auto-approve limit needs a named human before approval."""
  return amount_inr > policy_limit("auto_approve_limit_inr")


def may_system_approve(application_id: str) -> bool:
  return bool(assess_application(application_id)["auto_approve_allowed"])

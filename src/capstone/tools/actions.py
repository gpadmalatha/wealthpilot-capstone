import json
import logging
from datetime import datetime, timezone

from capstone.settings import get_settings
from capstone.tools.lookups import ApplicantNotFoundError
from capstone.tools.policy_engine import assess_application
from capstone.tools.repository import AUTHORITY_ORDER, get_repository, required_authority, signatory

logger = logging.getLogger(__name__)

HANDOFF_REASONS = (
    "policy_exception",
    "missing_information",
    "adverse_credit_history",
    "fraud_hold",
    "above_auto_approve_limit",
)


def _handoff_file():
  folder = get_settings().project_root / "runtime"
  folder.mkdir(exist_ok=True)
  return folder / "handoffs.jsonl"


def _existing_handoff(application_id: str):
  path = _handoff_file()
  if not path.exists():
    return None
  for line in path.read_text(encoding="utf-8").splitlines():
    record = json.loads(line)
    if record["application_id"] == application_id:
      return record
  return None


def hand_off_to_human(application_id: str, reason: str, summary: str) -> dict:
  """Escalate an application to a human reviewer and record why.

  Use when the system must not decide alone: a policy exception, missing
  information, adverse credit history (low bureau score or a large write-off),
  suspected fraud (fraud_hold only for document or revenue mismatches), or a
  loan above the auto-approve limit.
  Do not use to approve or decline a loan, or when the case is routine.
  Calling it again for the same application returns the existing hand-off.
  Pass only the application_id: the amount and approver come from the record.
  """
  application = get_repository().applications.get(application_id)
  if application is None:
    raise ApplicantNotFoundError(f"No application '{application_id}'.")
  applicant_id = application["applicant_id"]
  loan_amount_inr = int(application["requested_amount_inr"])  # from the data, never from the model
  if reason not in HANDOFF_REASONS:
    raise ValueError(
        f"Invalid hand-off reason '{reason}'. Allowed reasons are: {', '.join(HANDOFF_REASONS)}"
    )

  existing = _existing_handoff(application_id)
  if existing is not None:
    return existing

  authority = required_authority(loan_amount_inr)
  record = {
    "application_id": application_id,
    "applicant_id": applicant_id,
    "loan_amount_inr": loan_amount_inr,
    "reason": reason,
    "summary": summary,
    "required_authority": authority["authority"],
    "named_signatory_required": authority["named_signatory_required"] == "True",
    "created_at": datetime.now(timezone.utc).isoformat(),
  }
  with _handoff_file().open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(record) + "\n")
  logger.info("hand-off recorded for %s (%s)", application_id, reason)
  return record


DECISION_OUTCOMES = ("approved", "declined", "referred_to_siu")
SYSTEM_ACTOR = "system"


def _decision_file():
  folder = get_settings().project_root / "runtime"
  folder.mkdir(exist_ok=True)
  return folder / "decisions.jsonl"


def _existing_decision(application_id: str):
  path = _decision_file()
  if not path.exists():
    return None
  for line in path.read_text(encoding="utf-8").splitlines():
    record = json.loads(line)
    if record["application_id"] == application_id:
      return record
  return None


def check_signatory(signatory_id: str, amount_inr: int) -> dict:
  """Confirm a named person is active and has the authority this loan size needs. Raises ValueError otherwise."""
  person = signatory(signatory_id)
  if person is None:
    raise ValueError(f"Unknown signatory '{signatory_id}'.")
  if person["active"] != "True":
    raise ValueError(f"Signatory '{signatory_id}' is not active.")
  needed = required_authority(amount_inr)["authority"]
  if AUTHORITY_ORDER.index(person["authority"]) < AUTHORITY_ORDER.index(needed):
    raise ValueError(f"A {person['authority']} cannot sign a loan of {amount_inr} rupees; it needs {needed}.")
  return {"signatory_id": signatory_id, "authority": person["authority"]}


def record_decision(application_id: str, outcome: str, decided_by: str, note: str = "") -> dict:
  """Record the final decision on an application. Limits are enforced here, in code.

  Use only after the policy check. Automated decisions (decided_by 'system') are allowed only for clear
  declines and for approvals within the auto-approve limit. Anything else needs a named, active signatory
  with enough authority. Calling again for the same application returns the existing decision.
  """
  if outcome not in DECISION_OUTCOMES:
    raise ValueError(f"outcome must be one of {', '.join(DECISION_OUTCOMES)}")
  existing = _existing_decision(application_id)
  if existing is not None:
    return existing
  assessment = assess_application(application_id)
  reasons = assessment["reason_codes"]
  amount = assessment["requested_amount_inr"]
  automated = decided_by == SYSTEM_ACTOR

  if outcome == "approved":
    if assessment["status"] == "declined" or "FRAUD_HOLD" in reasons:
      raise ValueError("This application cannot be approved: it is policy-declined or under a fraud hold.")
    if automated and not assessment["auto_approve_allowed"]:
      raise ValueError("Automated approval is not permitted for this application; a named signatory is required.")
  if outcome == "declined" and automated and (assessment["status"] != "declined" or "FRAUD_HOLD" in reasons):
    raise ValueError("Only a clear policy decline may be declined automatically.")
  if outcome == "referred_to_siu" and "FRAUD_HOLD" not in reasons:
    raise ValueError("Only a fraud hold can be referred to the Special Investigation Unit.")
  if not automated:
    check_signatory(decided_by, amount)

  record = {
      "application_id": application_id,
      "applicant_id": assessment["applicant_id"],
      "outcome": outcome,
      "decided_by": decided_by,
      "grade": assessment["grade"],
      "reason_codes": reasons,
      "requested_amount_inr": amount,
      "note": note,
      "created_at": datetime.now(timezone.utc).isoformat(),
  }
  with _decision_file().open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(record) + "\n")
  logger.info("decision recorded for %s: %s by %s", application_id, outcome, decided_by)
  return record


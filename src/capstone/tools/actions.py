import json
import logging
from datetime import datetime, timezone

from capstone.settings import get_settings
from capstone.tools.lookups import ApplicantNotFoundError
from capstone.tools.repository import get_repository, required_authority

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
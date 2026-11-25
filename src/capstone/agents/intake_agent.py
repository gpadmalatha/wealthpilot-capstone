import json
import logging
import re
from dataclasses import dataclass
from typing import Callable, Optional

from pydantic import ValidationError

from capstone.llm.client import chat
from capstone.schemas.intake import FinancialSnapshot, LoanApplication, missing_field_names
from capstone.settings import get_settings

logger = logging.getLogger(__name__)


class IntakeError(Exception):
  """No valid LoanApplication could be produced; route this record to a human."""


@dataclass
class IntakeResult:
  application: LoanApplication
  attempts: int


def _load_prompt(name: str = "intake.md") -> str:
  path = get_settings().project_root / "prompts" / name
  return path.read_text(encoding="utf-8")


def extract_application(record: dict) -> IntakeResult:
  settings = get_settings()
  messages = [
      {"role": "system", "content": _load_prompt()},
      {"role": "user", "content": record["raw_narrative"]},
  ]

  last_error = None
  for attempt in range(1, settings.max_repair_attempts + 1):
    raw = chat(messages, json_mode=True)
    try:
      fields = json.loads(raw)
      application = LoanApplication(**{
          **fields,
          "application_id": record["application_id"],       # BLANK 1
          "applicant_id": record["applicant_id"],
          "channel": record["channel"],
          "received_at": record["received_at"],
          "raw_narrative": record["raw_narrative"],
      })
      return IntakeResult(application=application, attempts=attempt)
    except (json.JSONDecodeError, ValidationError, TypeError) as error:
      last_error = error
      logger.warning("intake attempt %d failed: %s", attempt, error)
      messages.append({"role": "assistant", "content": raw})     # BLANK 2
      messages.append({                                          # BLANK 3
          "role": "user",
          "content": f"That JSON failed validation:\n{error}\n"
                     "Return corrected JSON only.",
      })

  raise IntakeError(                                             # BLANK 4
      f"Intake failed for {record['application_id']} after "
      f"{settings.max_repair_attempts} attempts: {last_error}"
  )


# ---- the other two ways an application enters the system. All three produce the same LoanApplication.
def load_application(application_id: str) -> LoanApplication:
  """Build the validated LoanApplication for a stored application (database path; no model involved).

  The bureau score is not part of the stored application: it is pulled from the bureau later, so it starts
  out listed in missing_fields. Names, city and language are never copied (fair lending).
  """
  from capstone.tools.assessments import _application_and_applicant  # local import: tools depend on this module's schema

  application, applicant = _application_and_applicant(application_id)
  money = FinancialSnapshot(
      annual_revenue_inr=int(application["declared_annual_revenue_inr"]),
      existing_annual_debt_service_inr=int(application["existing_annual_debt_service_inr"]),
      current_assets_inr=int(application["current_assets_inr"]),
      current_liabilities_inr=int(application["current_liabilities_inr"]),
      collateral_value_inr=int(application["collateral_value_inr"]),
      ebitda_inr=int(applicant["ebitda_inr"]),
      existing_debt_inr=int(applicant["existing_debt_inr"]),
      months_operating=int(applicant["months_operating"]),
  )
  top = {"requested_amount_inr": int(application["requested_amount_inr"]),
         "requested_tenor_months": int(application["requested_tenor_months"]),
         "sector": applicant["sector"], "bureau_score": None}
  return LoanApplication(
      application_id=application_id,
      applicant_id=application["applicant_id"],
      sector=top["sector"],
      received_at=application["received_on"],
      purpose=application["purpose"],
      requested_amount_inr=top["requested_amount_inr"],
      requested_tenor_months=top["requested_tenor_months"],
      declared_financials=money,
      missing_fields=missing_field_names(top, money.model_dump()),
  )


TEXT_REQUEST_ID = "free-text-request"
TEXT_KEYS = {"sector", "amount", "tenor", "months_operating", "annual_revenue", "ebitda", "existing_debt",
             "existing_debt_service", "bureau_score", "current_assets", "current_liabilities", "collateral"}


def application_from_extraction(fields: dict) -> LoanApplication:
  """Turn the free-text extraction (flat keys) into the same LoanApplication. Raises ValidationError if invalid."""
  money = FinancialSnapshot(
      annual_revenue_inr=fields.get("annual_revenue"), ebitda_inr=fields.get("ebitda"),
      existing_debt_inr=fields.get("existing_debt"), existing_annual_debt_service_inr=fields.get("existing_debt_service"),
      current_assets_inr=fields.get("current_assets"), current_liabilities_inr=fields.get("current_liabilities"),
      collateral_value_inr=fields.get("collateral"), months_operating=fields.get("months_operating"),
  )
  top = {"requested_amount_inr": fields.get("amount"), "requested_tenor_months": fields.get("tenor"),
         "sector": fields.get("sector"), "bureau_score": fields.get("bureau_score")}
  return LoanApplication(
      application_id=TEXT_REQUEST_ID, applicant_id=TEXT_REQUEST_ID, **top, declared_financials=money,
      missing_fields=missing_field_names(top, money.model_dump()),
  )


def extract_from_text(text: str, llm: Callable[..., str] = chat) -> Optional[LoanApplication]:
  """Free-text request -> validated LoanApplication, or None if no valid object could be produced.

  Two checks in code, with a bounded repair loop: the schema, and every number must appear in the text.
  """
  messages = [{"role": "system", "content": _load_prompt("application_extract.md")}, {"role": "user", "content": text}]
  digits = text.replace(",", "")
  for _ in range(get_settings().max_repair_attempts):
    reply = llm(messages, json_mode=True)
    try:
      fields = json.loads(reply)
      if not isinstance(fields, dict):
        raise ValueError("reply must be a JSON object")
      unknown = set(fields) - TEXT_KEYS
      if unknown:
        raise ValueError(f"unexpected keys: {sorted(unknown)}")
      invented = [k for k, v in fields.items() if isinstance(v, int) and not re.search(rf"(?<!\d){v}(?!\d)", digits)]
      if invented:
        raise ValueError(f"these numbers do not appear in the text: {invented}. Use null when a figure is not stated.")
      return application_from_extraction(fields)
    except (ValueError, ValidationError) as error:
      messages += [{"role": "assistant", "content": reply}, {"role": "user", "content": f"Invalid: {error}. Return corrected JSON only."}]
  return None


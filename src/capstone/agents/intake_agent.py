import json
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from capstone.llm.client import chat
from capstone.schemas.intake import LoanApplication
from capstone.settings import get_settings

logger = logging.getLogger(__name__)


class IntakeError(Exception):
  """No valid LoanApplication could be produced; route this record to a human."""


@dataclass
class IntakeResult:
  application: LoanApplication
  attempts: int


def _load_prompt() -> str:
  path = get_settings().project_root / "prompts" / "intake.md"
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
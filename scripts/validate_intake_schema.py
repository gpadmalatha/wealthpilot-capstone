"""Validate every intake record against the LoanApplication schema.

Run from the project root:  python scripts/validate_intake_schema.py
Prints how many records pass and the most common reasons the rest fail.
"""
import json
from collections import Counter

from pydantic import ValidationError

from capstone.schemas.intake import LoanApplication
from capstone.settings import get_settings

# Fields the toolkit adds for its own bookkeeping, or that must never reach the model.
NOT_FOR_SCHEMA = ("ground_truth", "record_id")


def main() -> None:
  settings = get_settings()
  path = (settings.project_root / "data" / settings.capstone_domain
          / "intake" / "records.jsonl")
  records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

  passed = 0
  reasons: Counter = Counter()
  for record in records:
    payload = {k: v for k, v in record.items() if k not in NOT_FOR_SCHEMA}
    payload["missing_fields"] = record["ground_truth"]["missing_fields"]
    try:
      LoanApplication(**payload)
      passed += 1
    except ValidationError as error:
      for item in error.errors():
        where = ".".join(str(part) for part in item["loc"]) or "model"
        reasons[(item["type"], where, item["msg"][:80])] += 1

  print(f"{passed} of {len(records)} records valid")
  for (kind, where, message), count in reasons.most_common(10):
    print(f"  {count:>4}  {kind}  {where}  {message}")


if __name__ == "__main__":
  main()

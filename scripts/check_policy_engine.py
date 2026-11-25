"""Check the policy engine against the reference table on all applications (evaluator tooling, not part of the agent path).

Prints how many applications agree on grade, status and reason codes. Writes docs/m5_policy_engine_check.txt.
"""
import logging

from capstone.settings import get_settings
from capstone.tools.policy_engine import assess_application
from capstone.tools.repository import read_table

BAND_BY_STATUS = {"declined": "decline", "borderline": "borderline", "approvable": "approve"}


def main() -> None:
  logging.basicConfig(level=logging.WARNING)
  reference = {row["application_id"]: row for row in read_table("underwriting_reference")}
  total = grade_ok = band_ok = reasons_ok = auto_ok = 0
  mismatches: list[str] = []
  for application_id, row in reference.items():
    result = assess_application(application_id)
    total += 1
    grade_ok += result["grade"] == row["internal_grade"]
    band_ok += BAND_BY_STATUS[result["status"]] == row["risk_band"]
    same_reasons = set(result["reason_codes"]) == set(row["reason_codes"].split(";"))
    reasons_ok += same_reasons
    auto_ok += result["auto_approve_allowed"] == (row["auto_approve_allowed"] == "True")
    if not same_reasons and len(mismatches) < 8:
      mismatches.append(f"  {application_id}: engine={sorted(result['reason_codes'])} reference={row['reason_codes']}")
  lines = [
      f"applications checked: {total}",
      f"grade matches:        {grade_ok}/{total}",
      f"status matches:       {band_ok}/{total}",
      f"reason codes match:   {reasons_ok}/{total}",
      f"auto-approve matches: {auto_ok}/{total}",
  ] + (["first differences:"] + mismatches if mismatches else [])
  report = get_settings().project_root / "docs" / "m5_policy_engine_check.txt"
  report.write_text("\n".join(lines) + "\n", encoding="utf-8")
  print("\n".join(lines))


if __name__ == "__main__":
  main()

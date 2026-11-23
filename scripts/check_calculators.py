"""Check the DSCR calculator against the answer key in the mock data.

Run from the project root:  python scripts/check_calculators.py
For all 350 applications, recomputes the proposed annual debt service and the DSCR
from the raw tables and compares them with mock_api/underwriting_reference.csv.
"""
import csv

from capstone.settings import get_settings
from capstone.tools.calculators import calculate_dscr


def read_table(name: str) -> dict:
  path = (get_settings().project_root / "data" / get_settings().capstone_domain
          / "mock_api" / f"{name}.csv")
  with path.open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle))
  key = list(rows[0])[0]
  return {row[key]: row for row in rows}


def main() -> None:
  applicants = read_table("applicants")
  loans = read_table("loan_applications")
  reference = read_table("underwriting_reference")
  limits = read_table("policy_limits")
  assessment_rate = float(limits["assessment_rate_pct"]["value"])

  mismatches = []
  for application_id, loan in loans.items():
    applicant = applicants[loan["applicant_id"]]
    expected = reference[application_id]
    result = calculate_dscr(
        ebitda_inr=int(applicant["ebitda_inr"]),
        existing_annual_debt_service_inr=int(loan["existing_annual_debt_service_inr"]),
        loan_amount_inr=int(loan["requested_amount_inr"]),
        tenor_months=int(loan["requested_tenor_months"]),
        assessment_rate_pct=assessment_rate,
    )
    same_debt_service = (
        result["proposed_annual_debt_service_inr"]
        == int(expected["proposed_annual_debt_service_inr"]))
    same_dscr = abs(result["dscr"] - float(expected["dscr"])) <= 0.0101
    if not (same_debt_service and same_dscr):
      mismatches.append((application_id, result, expected["dscr"],
                         expected["proposed_annual_debt_service_inr"]))

  print(f"{len(loans) - len(mismatches)} of {len(loans)} applications match the reference")
  for application_id, result, dscr, debt_service in mismatches[:5]:
    print(f"  {application_id}: got {result}, expected dscr={dscr} debt_service={debt_service}")


if __name__ == "__main__":
  main()

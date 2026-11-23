"""Entity-scoped lookups over the mock bureau and bank-statement tables."""
from capstone.tools.repository import get_repository


class ApplicantNotFoundError(LookupError):
  """No record exists for this applicant_id."""


def get_bureau_report(applicant_id: str) -> dict:
  """Fetch the credit-bureau report for one applicant.

  Use when you need the applicant's bureau score or repayment history before
  scoring. Do not use for bank or revenue data (use get_bank_statements).
  Returns bureau_score (300-900), enquiries_last_6m, active_trade_lines,
  dpd_30_last_12m (count of 30-days-past-due events), dpd_90_ever (bool),
  written_off_amount_inr and report_pulled_on.
  """
  row = get_repository().bureau.get(applicant_id)
  if row is None:
    raise ApplicantNotFoundError(f"No bureau report for applicant '{applicant_id}'.")
  return {
      "applicant_id": applicant_id,
      "bureau_score": int(row["bureau_score"]),
      "enquiries_last_6m": int(row["enquiries_last_6m"]),
      "active_trade_lines": int(row["active_trade_lines"]),
      "dpd_30_last_12m": int(row["dpd_30_last_12m"]),
      "dpd_90_ever": row["dpd_90_ever"] == "True",
      "written_off_amount_inr": int(row["written_off_amount_inr"]),
      "report_pulled_on": row["report_pulled_on"],
  }


def get_bank_statements(applicant_id: str, months: int = 6) -> dict:
  """Fetch the most recent monthly bank statement summaries for one applicant.

  Use to verify revenue and cash-flow behaviour (inflows, outflows, balances,
  bounced instruments). Do not use for credit history (use get_bureau_report).
  Returns up to `months` months, newest first, one entry per month. Fewer months
  than requested may come back: check shortfall_months, and ask the applicant for
  the missing statements instead of assuming. Duplicate months in the source are
  removed (see duplicate_rows_dropped). An applicant with no statements returns
  an empty list, not an error.
  """
  repo = get_repository()
  if applicant_id not in repo.applicants:
    raise ApplicantNotFoundError(f"Unknown applicant '{applicant_id}'.")
  if months < 1:
    raise ValueError("months must be at least 1.")

  rows = repo.statements.get(applicant_id, [])

  # One row per month: when a month appears twice, keep the larger statement_id.
  by_month: dict[str, dict] = {}
  for row in rows:
    kept = by_month.get(row["month"])
    if kept is None or row["statement_id"] > kept["statement_id"]:
      by_month[row["month"]] = row
  duplicates_dropped = len(rows) - len(by_month)

  # Newest month first ("2026-07" sorts correctly as text), then keep `months`.
  newest_first = sorted(by_month.values(), key=lambda r: r["month"], reverse=True)
  chosen = newest_first[:months]

  return {
      "applicant_id": applicant_id,
      "months_requested": months,
      "months_returned": len(chosen),
      "shortfall_months": max(months - len(chosen), 0),
      "duplicate_rows_dropped": duplicates_dropped,
      "statements": [
          {
              "month": r["month"],
              "inflow_inr": int(r["inflow_inr"]),
              "outflow_inr": int(r["outflow_inr"]),
              "closing_balance_inr": int(r["closing_balance_inr"]),
              "bounced_instruments": int(r["bounced_instruments"]),
              "avg_daily_balance_inr": int(r["avg_daily_balance_inr"]),
          }
          for r in chosen
      ],
  }

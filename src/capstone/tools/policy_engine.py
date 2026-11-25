"""Deterministic underwriting policy engine: Credit Policy Manual section 4 applied to one application.

No model is involved. The workflow, the committee agents and the MCP server all call
assess_application, so a decision never depends on which entry point asked.
Inputs are financial and bureau facts only. Name, city, community and language are never read here.
"""
from typing import Optional

from capstone.tools.assessments import _application_and_applicant
from capstone.tools.calculators import calculate_dscr
from capstone.tools.lookups import get_bank_statements, get_bureau_report
from capstone.tools.repository import get_repository, grade_table, policy_limit, sector_table

STATUS_DECLINED = "declined"
STATUS_BORDERLINE = "borderline"
STATUS_APPROVABLE = "approvable"
GRADES_REQUIRING_REVIEW = ("C2", "D1")
WORST_GRADE = "D2"


def assign_grade(dscr: float, bureau_score: int) -> dict:
  """The best grade whose minimum DSCR and minimum bureau score are both met; D2 if none."""
  for grade in grade_table():
    if grade["grade"] == WORST_GRADE:
      continue
    if dscr >= float(grade["min_dscr"]) and bureau_score >= int(grade["min_bureau_score"]):
      return grade
  return next(grade for grade in grade_table() if grade["grade"] == WORST_GRADE)


def _revenue_variance_pct(declared: int, verified: int) -> float:
  return abs(declared - verified) / verified * 100 if verified else 0.0


def assess_application(application_id: str, bureau: Optional[dict] = None) -> dict:
  """Apply the credit policy to one application and return grade, ratios, reason codes and status.

  Use for the policy verdict on an application. Do not use to approve or decline: it only
  classifies (declined, borderline, approvable) and says whether a human must sign off.
  Returns grade, dscr, leverage_ratio, current_ratio, revenue_variance_pct, reason_codes,
  status, auto_approve_allowed and requires_human_signoff.
  """
  application, applicant = _application_and_applicant(application_id)
  bureau = bureau or get_bureau_report(application["applicant_id"])  # a report pulled earlier may be passed in
  sector = sector_table()[applicant["sector"]]

  amount = int(application["requested_amount_inr"])
  tenor = int(application["requested_tenor_months"])
  ebitda = int(applicant["ebitda_inr"])
  existing_debt = int(applicant["existing_debt_inr"])
  months_operating = int(applicant["months_operating"])
  assessment_rate = policy_limit("assessment_rate_pct")

  dscr_result = calculate_dscr(ebitda, int(application["existing_annual_debt_service_inr"]), amount, tenor, assessment_rate)
  dscr = dscr_result["dscr"]
  leverage = round((existing_debt + amount) / ebitda, 2) if ebitda else float("inf")
  current_liabilities = int(application["current_liabilities_inr"])
  current_ratio = round(int(application["current_assets_inr"]) / current_liabilities, 2) if current_liabilities else float("inf")
  variance = round(_revenue_variance_pct(int(application["declared_annual_revenue_inr"]), int(applicant["annual_revenue_inr"])), 1)

  grade = assign_grade(dscr, bureau["bureau_score"])
  dscr_floor = max(policy_limit("min_dscr"), float(sector["dscr_floor"]))
  tenor_limit = min(int(grade["max_tenor_months"]), int(sector["max_tenor_months"]))
  collateral_required = amount * float(grade["collateral_cover_pct"]) / 100

  reasons: list[str] = []
  if dscr < dscr_floor:
    reasons.append("DSCR_BELOW_FLOOR")
  if months_operating < policy_limit("min_months_operating") or bureau["active_trade_lines"] == 0:
    reasons.append("THIN_FILE")
  if bureau["bureau_score"] < policy_limit("min_bureau_score"):
    reasons.append("ADVERSE_BUREAU")
  if bureau["dpd_90_ever"] or bureau["written_off_amount_inr"] >= policy_limit("write_off_limit_inr"):
    reasons.append("PAST_DELINQUENCY")
  if variance > policy_limit("revenue_tolerance_pct"):
    reasons.append("DOC_MISMATCH")
  if variance > policy_limit("fraud_hold_pct"):
    reasons.append("FRAUD_HOLD")  # beyond the fraud threshold both codes apply
  if sector["at_sector_cap"] == "True":
    reasons.append("SECTOR_CAP")
  if leverage > policy_limit("max_leverage"):
    reasons.append("LEVERAGE_ABOVE_LIMIT")
  if current_ratio < policy_limit("min_current_ratio"):
    reasons.append("LIQUIDITY_BELOW_FLOOR")
  clear_decline = dscr < 1.0 or "ADVERSE_BUREAU" in reasons or "THIN_FILE" in reasons and months_operating < policy_limit("min_months_operating") or grade["grade"] == WORST_GRADE
  if not clear_decline:
    # Tenor and collateral are tested against the assigned grade, so they only apply once the file is not already declined.
    if tenor > tenor_limit:
      reasons.append("TENOR_ABOVE_LIMIT")
    if int(application["collateral_value_inr"]) < collateral_required:
      reasons.append("COLLATERAL_SHORTFALL")
    if grade["grade"] in GRADES_REQUIRING_REVIEW:
      reasons.append("GRADE_REQUIRES_REVIEW")
  if clear_decline:
    status = STATUS_DECLINED
  elif reasons:
    status = STATUS_BORDERLINE
  else:
    status = STATUS_APPROVABLE
    reasons = ["APPROVED_STANDARD"]

  auto_allowed = (
      status == STATUS_APPROVABLE
      and grade["auto_approve_allowed"] == "True"
      and amount <= policy_limit("auto_approve_limit_inr")
  )
  return {
      "application_id": application_id,
      "applicant_id": application["applicant_id"],
      "requested_amount_inr": amount,
      "grade": grade["grade"],
      "dscr": dscr,
      "dscr_floor": dscr_floor,
      "leverage_ratio": leverage,
      "current_ratio": current_ratio,
      "revenue_variance_pct": variance,
      "reason_codes": reasons,
      "status": status,
      "auto_approve_allowed": auto_allowed,
      "requires_human_signoff": not auto_allowed,
  }


def verify_documents(application_id: str) -> dict:
  """Check declared revenue against verified revenue and report how many bank statements exist.

  Use to verify documents before scoring. Do not use for the credit verdict (use assess_application).
  Returns revenue_variance_pct, revenue_flag (ok, doc_mismatch or fraud_hold) and statement coverage.
  """
  application, applicant = _application_and_applicant(application_id)
  variance = round(_revenue_variance_pct(int(application["declared_annual_revenue_inr"]), int(applicant["annual_revenue_inr"])), 1)
  if variance > policy_limit("fraud_hold_pct"):
    flag = "fraud_hold"
  elif variance > policy_limit("revenue_tolerance_pct"):
    flag = "doc_mismatch"
  else:
    flag = "ok"
  statements = get_bank_statements(application["applicant_id"], months=6)
  return {
      "application_id": application_id,
      "declared_revenue_inr": int(application["declared_annual_revenue_inr"]),
      "verified_revenue_inr": int(applicant["annual_revenue_inr"]),
      "revenue_variance_pct": variance,
      "revenue_flag": flag,
      "statement_months_available": statements["months_returned"],
      "statement_shortfall_months": statements["shortfall_months"],
  }


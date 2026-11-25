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


REQUIRED_INPUTS = ("amount", "tenor", "ebitda", "existing_debt", "existing_debt_service", "current_assets",
                   "current_liabilities", "collateral", "months_operating", "sector", "bureau_score")


def assess_inputs(facts: dict) -> dict:
  """Pure policy verdict from normalized facts. No lookups, no model: the same facts always give the same answer.

  facts needs: amount, tenor, ebitda, existing_debt, existing_debt_service, current_assets, current_liabilities,
  collateral, months_operating, sector, bureau_score. Optional: active_trade_lines, dpd_90_ever, written_off_amount_inr,
  revenue_variance_pct. A missing required figure gives status borderline with INCOMPLETE_APPLICATION (policy 4.07).
  """
  missing = [name for name in REQUIRED_INPUTS if facts.get(name) is None]
  if missing:
    return {"grade": None, "dscr": None, "reason_codes": ["INCOMPLETE_APPLICATION"], "status": STATUS_BORDERLINE, "missing": missing,
            "auto_approve_allowed": False, "auto_decline_allowed": False, "requires_human_signoff": True,
            "requested_amount_inr": facts.get("amount")}
  sector = sector_table()[facts["sector"]]
  amount, tenor, ebitda = int(facts["amount"]), int(facts["tenor"]), int(facts["ebitda"])
  months_operating = int(facts["months_operating"])
  bureau_score = int(facts["bureau_score"])
  trade_lines = facts.get("active_trade_lines", 1)  # not in free-text applications: assume the file is not thin on this count
  variance = float(facts.get("revenue_variance_pct") or 0.0)

  dscr_result = calculate_dscr(ebitda, int(facts["existing_debt_service"]), amount, tenor, policy_limit("assessment_rate_pct"))
  dscr = dscr_result["dscr"]
  new_service = dscr_result["proposed_annual_debt_service_inr"]
  leverage = round((int(facts["existing_debt"]) + amount) / ebitda, 2) if ebitda else float("inf")
  liabilities = int(facts["current_liabilities"])
  current_ratio = round(int(facts["current_assets"]) / liabilities, 2) if liabilities else float("inf")

  grade = assign_grade(dscr, bureau_score)
  dscr_floor = max(policy_limit("min_dscr"), float(sector["dscr_floor"]))
  tenor_limit = min(int(grade["max_tenor_months"]), int(sector["max_tenor_months"]))
  collateral_required = amount * float(grade["collateral_cover_pct"]) / 100

  reasons: list[str] = []
  if dscr < dscr_floor:
    reasons.append("DSCR_BELOW_FLOOR")
  if months_operating < policy_limit("min_months_operating") or trade_lines == 0:
    reasons.append("THIN_FILE")
  if bureau_score < policy_limit("min_bureau_score"):
    reasons.append("ADVERSE_BUREAU")
  if facts.get("dpd_90_ever") or int(facts.get("written_off_amount_inr") or 0) >= policy_limit("write_off_limit_inr"):
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
  short_history = months_operating < policy_limit("min_months_operating")
  clear_decline = dscr < 1.0 or "ADVERSE_BUREAU" in reasons or short_history or grade["grade"] == WORST_GRADE
  if not clear_decline:
    # Tenor and collateral are tested against the assigned grade, so they only apply once the file is not already declined.
    if tenor > tenor_limit:
      reasons.append("TENOR_ABOVE_LIMIT")
    if int(facts["collateral"]) < collateral_required:
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
  # Policy 4.08.2: every decline needs human sign-off, except the one the manual says the system issues itself (4.02.3):
  # operating history under 24 months. Fraud holds are never decided by the system.
  auto_decline = status == STATUS_DECLINED and short_history and "FRAUD_HOLD" not in reasons
  return {
      "requested_amount_inr": amount,
      "grade": grade["grade"],
      "dscr": dscr,
      "dscr_floor": dscr_floor,
      "proposed_annual_debt_service_inr": new_service,
      "total_annual_debt_service_inr": int(facts["existing_debt_service"]) + new_service,
      "leverage_ratio": leverage,
      "current_ratio": current_ratio,
      "revenue_variance_pct": round(variance, 1),
      "reason_codes": reasons,
      "status": status,
      "auto_approve_allowed": auto_allowed,
      "auto_decline_allowed": auto_decline,
      "requires_human_signoff": not (auto_allowed or auto_decline),
  }


def assess_application(application_id: str, bureau: Optional[dict] = None) -> dict:
  """Apply the credit policy to one application and return grade, ratios, reason codes and status.

  Use for the policy verdict on an application. Do not use to approve or decline: it only
  classifies (declined, borderline, approvable) and says whether a human must sign off.
  Returns grade, dscr, leverage_ratio, current_ratio, revenue_variance_pct, reason_codes,
  status, auto_approve_allowed, auto_decline_allowed and requires_human_signoff.
  """
  application, applicant = _application_and_applicant(application_id)
  bureau = bureau or get_bureau_report(application["applicant_id"])  # a report pulled earlier may be passed in
  facts = {
      "amount": application["requested_amount_inr"],
      "tenor": application["requested_tenor_months"],
      "ebitda": applicant["ebitda_inr"],
      "existing_debt": applicant["existing_debt_inr"],
      "existing_debt_service": application["existing_annual_debt_service_inr"],
      "current_assets": application["current_assets_inr"],
      "current_liabilities": application["current_liabilities_inr"],
      "collateral": application["collateral_value_inr"],
      "months_operating": applicant["months_operating"],
      "sector": applicant["sector"],
      "bureau_score": bureau["bureau_score"],
      "active_trade_lines": bureau["active_trade_lines"],
      "dpd_90_ever": bureau["dpd_90_ever"],
      "written_off_amount_inr": bureau["written_off_amount_inr"],
      "revenue_variance_pct": _revenue_variance_pct(int(application["declared_annual_revenue_inr"]), int(applicant["annual_revenue_inr"])),
  }
  return {"application_id": application_id, "applicant_id": application["applicant_id"], **assess_inputs(facts)}


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


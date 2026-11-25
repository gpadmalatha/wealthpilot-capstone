"""Application-level tools. The model names an application; code supplies the numbers.

Policy limits (assessment rate, DSCR floors, approval authority) are read from
the seed data here, so the model can neither invent nor understate them.
"""
from capstone.tools.calculators import CalculationInputError, calculate_dscr, calculate_emi
from capstone.tools.lookups import ApplicantNotFoundError, get_bureau_report
from capstone.tools.repository import (
    get_repository,
    policy_limit,
    reference_rate,
    required_authority,
    sector_dscr_floor,
)

SUPPORTED_CURRENCIES = ("USD", "EUR", "GBP", "AED", "SGD")


def _application_and_applicant(application_id: str) -> tuple[dict, dict]:
  repository = get_repository()
  application = repository.applications.get(application_id)
  if application is None:
    raise ApplicantNotFoundError(f"No application '{application_id}'.")
  return application, repository.applicants[application["applicant_id"]]


def get_application(application_id: str) -> dict:
  """Fetch the validated loan application: requested amount and tenor, sector and declared financials.

  Use first, to learn the applicant_id, the requested amount and the sector.
  Do not use for bureau or bank-statement data (use get_bureau_report or
  get_bank_statements). Returns the intake LoanApplication (the same object every other step reads); the bureau
  score is listed in missing_fields until it is pulled. Returns no personal identifiers such as name or city.
  """
  from capstone.agents.intake_agent import load_application  # local import: intake builds on this module's lookups

  return load_application(application_id).model_dump(mode="json", exclude_none=True)


def assess_dscr(application_id: str) -> dict:
  """Compute the debt-service coverage ratio (DSCR) for an application and compare it to policy.

  Use after get_application when you need the DSCR verdict. Do not pass amounts
  yourself: the tool reads them from the application and uses the bank's
  assessment rate. Returns dscr, the floor that applies (the higher of the bank
  minimum and the sector floor) and meets_floor.
  """
  application, applicant = _application_and_applicant(application_id)
  result = calculate_dscr(
      ebitda_inr=int(applicant["ebitda_inr"]),
      existing_annual_debt_service_inr=int(application["existing_annual_debt_service_inr"]),
      loan_amount_inr=int(application["requested_amount_inr"]),
      tenor_months=int(application["requested_tenor_months"]),
      assessment_rate_pct=policy_limit("assessment_rate_pct"),
  )
  floor = max(policy_limit("min_dscr"), sector_dscr_floor(applicant["sector"]))
  return {**result, "dscr_floor": floor, "meets_floor": result["dscr"] >= floor}


def check_bureau_policy(applicant_id: str) -> dict:
  """Compare an applicant's bureau record with bank policy and say whether it is adverse.

  Use after get_bureau_report to get the policy verdict on the score and on any
  written-off amount. Do not use for revenue or cash-flow checks. Returns
  bureau_score, min_bureau_score, score_is_adverse, written_off_amount_inr,
  write_off_limit_inr and past_delinquency.
  """
  report = get_bureau_report(applicant_id)
  minimum = int(policy_limit("min_bureau_score"))
  write_off_limit = int(policy_limit("write_off_limit_inr"))
  return {
      "applicant_id": applicant_id,
      "bureau_score": report["bureau_score"],
      "min_bureau_score": minimum,
      "score_is_adverse": report["bureau_score"] < minimum,
      "written_off_amount_inr": report["written_off_amount_inr"],
      "write_off_limit_inr": write_off_limit,
      "past_delinquency": report["written_off_amount_inr"] >= write_off_limit,
  }


def check_approval_authority(application_id: str) -> dict:
  """Say who may approve this application's loan amount, and whether the system may approve alone.

  Use before deciding whether to hand off. Do not use to approve a loan. Returns
  required_authority, named_signatory_required and auto_approve_allowed.
  """
  application, _ = _application_and_applicant(application_id)
  amount = int(application["requested_amount_inr"])
  authority = required_authority(amount)
  return {
      "application_id": application_id,
      "requested_amount_inr": amount,
      "required_authority": authority["authority"],
      "named_signatory_required": authority["named_signatory_required"] == "True",
      "auto_approve_allowed": amount <= policy_limit("auto_approve_limit_inr"),
  }


def monthly_instalment(principal_inr: float, annual_rate_pct: float, tenor_months: int) -> dict:
  """Compute the monthly instalment (EMI) for a hypothetical loan.

  Use for what-if questions (different amount, rate or tenor). Do not use for the
  application's own DSCR (use assess_dscr). Amounts in INR, rate in percent per year.
  """
  emi = calculate_emi(principal_inr, annual_rate_pct, tenor_months)
  return {"emi_inr": round(emi), "total_repayment_inr": round(emi * tenor_months)}


def convert_to_inr(amount: float, currency: str) -> dict:
  """Convert a foreign-currency amount (for example export receivables) to INR at the bank's reference rate.

  Use when a figure is stated in USD, EUR, GBP, AED or SGD. Do not use for INR amounts.
  """
  code = currency.upper()
  if code not in SUPPORTED_CURRENCIES:
    raise CalculationInputError(f"Unsupported currency '{currency}'. Use one of: {', '.join(SUPPORTED_CURRENCIES)}")
  if amount < 0:
    raise CalculationInputError("amount cannot be negative.")
  rate = reference_rate(f"{code}_INR")
  return {"currency": code, "rate_to_inr": rate, "amount_inr": round(amount * rate)}

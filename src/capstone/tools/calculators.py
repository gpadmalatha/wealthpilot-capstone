"""Deterministic loan calculators. Units are in the names: inr, pct, months."""


class CalculationInputError(ValueError):
  """Raised when financial calculation inputs fail validation."""


def calculate_emi(principal_inr: float, annual_rate_pct: float, tenor_months: int) -> float:
  """Monthly instalment (EMI) for a loan. Amounts in INR, rate in percent per year."""
  if principal_inr <= 0:
    raise CalculationInputError("principal_inr must be greater than 0.")
  if tenor_months <= 0:
    raise CalculationInputError("tenor_months must be greater than 0.")
  if annual_rate_pct < 0:
    raise CalculationInputError("annual_rate_pct cannot be negative.")

  if annual_rate_pct == 0:
    return principal_inr / tenor_months

  monthly_rate = annual_rate_pct / 100 / 12
  growth = (1 + monthly_rate) ** tenor_months
  return principal_inr * monthly_rate * growth / (growth - 1)


def calculate_dscr(
    ebitda_inr: float,
    existing_annual_debt_service_inr: float,
    loan_amount_inr: float,
    tenor_months: int,
    assessment_rate_pct: float,
) -> dict:
  """Debt service coverage ratio after the proposed loan.

  Returns {"dscr": <rounded to 2 decimals>,
           "proposed_annual_debt_service_inr": <rounded to whole rupees, int>}.
  """
  if ebitda_inr < 0:
    raise CalculationInputError("ebitda_inr cannot be negative.")
  if existing_annual_debt_service_inr < 0:
    raise CalculationInputError("existing_annual_debt_service_inr cannot be negative.")

  monthly_instalment = calculate_emi(loan_amount_inr, assessment_rate_pct, tenor_months)
  proposed = 12 * monthly_instalment
  total_debt_service = existing_annual_debt_service_inr + proposed

  if total_debt_service == 0:
    raise CalculationInputError("Total annual debt service cannot be zero.")

  return {
      "dscr": round(ebitda_inr / total_debt_service, 2),
      "proposed_annual_debt_service_inr": round(proposed),
  }

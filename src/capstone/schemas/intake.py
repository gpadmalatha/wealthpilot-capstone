from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Values below come from the generated WealthPilot data:
#   sectors  = the 8 rows of mock_api/sector_policies
#   channels = the intake prompt's channel list (re-check against intake/records.jsonl)
SectorType = Literal[
    "Textiles",
    "Food Processing",
    "Light Engineering",
    "Logistics",
    "Retail Trade",
    "Auto Components",
    "Pharma Packaging",
    "IT Services",
]

ChannelType = Literal["web_form", "relationship_manager_email", "partner_api"]

# Single source of truth for fields required for scoring.
# Used by the cross-field validator to enforce missing_fields consistency.
SCORING_REQUIRED_FIELDS: tuple[str, ...] = (
    "requested_amount_inr",
    "requested_tenor_months",
    "bureau_score",
    "sector",
    "declared_financials",
)


class FinancialSnapshot(BaseModel):
  """Applicant's declared financial metrics stored as integer rupees."""

  model_config = ConfigDict(extra="forbid")

  annual_revenue_inr: Optional[int] = Field(default=None, ge=0)
  existing_annual_debt_service_inr: Optional[int] = Field(default=None, ge=0)
  current_assets_inr: Optional[int] = Field(default=None, ge=0)
  current_liabilities_inr: Optional[int] = Field(default=None, ge=0)
  collateral_value_inr: Optional[int] = Field(default=None, ge=0)


class LoanApplication(BaseModel):
  """Loan application record with strict schema boundaries and cross-field checks."""

  # Forbids extra keys (e.g., ground_truth leakage or hallucinated fields).
  # Note: Fair-lending proxy fields (proprietor_name, city, application_language)
  # are intentionally excluded and must be stripped before model validation.
  model_config = ConfigDict(extra="forbid")

  # Required identifiers
  application_id: str
  applicant_id: str

  # Core application metadata
  business_name: Optional[str] = None
  sector: Optional[SectorType] = None
  channel: Optional[ChannelType] = None
  received_at: Optional[datetime] = None
  raw_narrative: Optional[str] = None
  purpose: Optional[str] = None

  # Loan terms and credit metrics (simple bounds enforced directly via Field)
  requested_amount_inr: Optional[int] = Field(default=None, gt=0)
  requested_tenor_months: Optional[int] = Field(default=None, gt=0)
  bureau_score: Optional[int] = None
  declared_financials: Optional[FinancialSnapshot] = None

  # Audit trail of missing fields
  missing_fields: list[str] = Field(default_factory=list)

  # Single-field value-rule validator with business context
  @field_validator("bureau_score")
  @classmethod
  def validate_bureau_score_range(cls, value: Optional[int]) -> Optional[int]:
    # Business reason: Indian credit bureaus (CIBIL, Experian, CRIF, Equifax)
    # issue scores strictly within 300-900. Values outside this window represent
    # thin-file/no-hit codes (e.g., -1, 0) or ingestion errors.
    if value is not None and not (300 <= value <= 900):
      raise ValueError(
          f"bureau_score must be between 300 and 900 (got {value})."
      )
    return value

  # Cross-field validator comparing field values against missing_fields
  @model_validator(mode="after")
  def validate_missing_fields_consistency(self) -> "LoanApplication":
    # Business reason: missing_fields must accurately reflect the actual state
    # of the record so downstream scoring and ground_truth evaluations do not
    # contradict themselves.
    declared_missing = set(self.missing_fields)
    valid_model_fields = set(type(self).model_fields.keys()) - {
        "missing_fields"
    }

    # 1. Every entry in missing_fields must actually be a known field and be None
    for field_name in declared_missing:
      if field_name not in valid_model_fields:
        raise ValueError(
            f"Unknown field '{field_name}' listed in missing_fields."
        )
      if getattr(self, field_name) is not None:
        raise ValueError(
            f"Contradiction: '{field_name}' is listed in missing_fields, "
            "but a non-null value was provided."
        )

    # 2. Every field required for scoring that is currently None must be listed
    for req_field in SCORING_REQUIRED_FIELDS:
      if getattr(self, req_field) is None and req_field not in declared_missing:
        raise ValueError(
            f"Scoring-required field '{req_field}' is None, so it must be "
            "included in missing_fields."
        )

    return self

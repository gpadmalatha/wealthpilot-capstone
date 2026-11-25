"""Read-only access to the seed tables in data/<domain>/mock_api.

Seed data is immutable: nothing here writes. Anything a tool needs to change
(for example a hand-off record) goes under runtime/, never into data/.
"""
import csv
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Optional

from capstone.settings import get_settings


def _mock_api_dir() -> Path:
  settings = get_settings()
  return settings.project_root / "data" / settings.capstone_domain / "mock_api"


def read_table(name: str) -> list[dict]:
  """Read one mock-API CSV as a list of rows (every value is a string)."""
  path = _mock_api_dir() / f"{name}.csv"
  with path.open(encoding="utf-8", newline="") as handle:
    return list(csv.DictReader(handle))


class Repository:
  """The tables the tools need, indexed by applicant."""

  def __init__(self) -> None:
    self.applicants = {row["applicant_id"]: row for row in read_table("applicants")}
    self.bureau = {row["applicant_id"]: row for row in read_table("bureau_reports")}
    self.applications = {row["application_id"]: row for row in read_table("loan_applications")}
    self.statements: dict[str, list[dict]] = defaultdict(list)
    for row in read_table("bank_statements"):
      self.statements[row["applicant_id"]].append(row)


@lru_cache
def get_repository() -> Repository:
  return Repository()

def required_authority(loan_amount_inr: int) -> dict:
  """Smallest approval authority whose limit covers the loan (a blank limit means no cap)."""
  rows = read_table("approval_authorities")
  for row in rows:
    limit = row["max_loan_inr"]
    if limit == "" or loan_amount_inr <= int(limit):
      return row
  raise ValueError("no approval authority configured")


def policy_limit(name: str) -> float:
  """One numeric bank policy limit from policy_limits (for example min_dscr)."""
  for row in read_table("policy_limits"):
    if row["limit"] == name:
      return float(row["value"])
  raise ValueError(f"unknown policy limit '{name}'")


def sector_dscr_floor(sector: str) -> float:
  """The DSCR floor for a sector from sector_policies."""
  for row in read_table("sector_policies"):
    if row["sector"] == sector:
      return float(row["dscr_floor"])
  raise ValueError(f"unknown sector '{sector}'")


def reference_rate(name: str) -> float:
  """A reference rate such as USD_INR from reference_rates."""
  for row in read_table("reference_rates"):
    if row["rate"] == name:
      return float(row["value"])
  raise ValueError(f"unknown reference rate '{name}'")


@lru_cache
def grade_table() -> list[dict]:
  """Risk grades best to worst (A1..D2), from risk_grades."""
  return read_table("risk_grades")


@lru_cache
def sector_table() -> dict[str, dict]:
  """Sector policies keyed by sector name."""
  return {row["sector"]: row for row in read_table("sector_policies")}


AUTHORITY_ORDER = ("Credit Officer", "Credit Committee", "Board Credit Committee")


def signatory(user_id: str) -> Optional[dict]:
  """One row of signatories, or None."""
  for row in read_table("signatories"):
    if row["user_id"] == user_id:
      return row
  return None


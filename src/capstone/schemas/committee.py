"""Typed outputs of the committee roles."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

Recommendation = Literal["approve", "decline", "refer"]
Verdict = Literal["accept", "revise", "reject", "escalate"]


class AnalystMemo(BaseModel):
  recommendation: Recommendation
  rationale: str = Field(min_length=1)
  key_facts: list[str] = Field(default_factory=list)
  conditions: list[str] = Field(default_factory=list)


class ReviewVerdict(BaseModel):
  reviewer: str = "reviewer"
  verdict: Verdict
  issues: list[str] = Field(default_factory=list)


class CommitteeResult(BaseModel):
  outcome: Literal["agreed", "rejected", "escalated", "exhausted", "unavailable"]
  final_recommendation: Recommendation
  rounds: int
  memo: Optional[AnalystMemo] = None
  verdict_log: list[dict] = Field(default_factory=list)

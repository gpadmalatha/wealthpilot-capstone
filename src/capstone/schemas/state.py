"""Workflow state shared by every node of the underwriting graph."""
import operator
from typing import Annotated, Optional, TypedDict


class WorkflowState(TypedDict, total=False):
  application_id: str
  application: dict
  bureau_report: dict
  bureau_source: str  # live | cache | unavailable
  bureau_log: list[str]
  verification: dict
  assessment: dict
  route: str  # auto_decline | auto_approve | human_review
  review_kind: str  # fraud_hold | borderline | signoff | decline_signoff | bureau_stale
  committee: dict  # advisory memo from the committee (M6); never a decision
  human_input: dict  # what the reviewer sent back when the workflow resumed
  review_error: Optional[str]
  review_attempts: int
  decision: dict
  outcome: str  # approved | declined | referred_to_siu | unresolved | intake_failed
  trail: Annotated[list[str], operator.add]  # nodes visited, appended by each node

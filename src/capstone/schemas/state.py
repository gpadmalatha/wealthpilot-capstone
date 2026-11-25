"""Workflow state shared by every node of the underwriting graph."""
import operator
from typing import Annotated, Optional, TypedDict


class WorkflowState(TypedDict, total=False):
  application_id: str
  application: dict
  memory: dict  # recalled facts, procedures and recent events for this applicant (M3 long-term memory)
  memory_hold: Optional[str]  # why remembered context sent the case to a human; memory can only tighten
  authority: dict  # who may approve this loan amount (check_approval_authority tool)
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
  tool_calls: Annotated[list[dict], operator.add]  # audit of every tool the nodes called
  trail: Annotated[list[str], operator.add]  # nodes visited, appended by each node

"""Underwriting workflow: intake -> document verification -> risk scoring -> conditional routing.

Clear policy declines and small clean approvals are decided automatically. Fraud holds, borderline cases and
approvals that need a signatory pause at a human checkpoint. The pause is persisted, so the run can be resumed
later, even from a new process. Side effects live in their own nodes AFTER the pause, so a resume never repeats one.
"""
import logging
from typing import Any, Callable, Optional

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from capstone.schemas.response import run_tool
from capstone.schemas.state import WorkflowState
from capstone.settings import get_settings
from capstone.tools.actions import SYSTEM_ACTOR, record_decision
from capstone.tools.assessments import get_application
from capstone.tools.policy_engine import assess_application, verify_documents
from capstone.workflows.approvals import review_kind, review_request

logger = logging.getLogger(__name__)


def intake(state: WorkflowState) -> dict:
  result = run_tool(get_application, application_id=state["application_id"])
  if not result.ok:
    return {"outcome": "intake_failed", "review_error": result.error.message, "trail": ["intake:failed"]}
  return {"application": result.data, "trail": ["intake"]}


def verify(state: WorkflowState) -> dict:
  result = run_tool(verify_documents, application_id=state["application_id"])
  return {"verification": result.data or {}, "trail": ["verify_documents"]}


def score(state: WorkflowState) -> dict:
  result = run_tool(assess_application, application_id=state["application_id"])
  if not result.ok:
    return {"outcome": "unresolved", "review_error": result.error.message, "trail": ["score_risk:failed"]}
  assessment = result.data
  if "FRAUD_HOLD" in assessment["reason_codes"]:
    route = "human_review"  # fraud is never decided automatically, even if the file is also a clear decline
  elif assessment["status"] == "declined":
    route = "auto_decline"
  elif assessment["auto_approve_allowed"]:
    route = "auto_approve"
  else:
    route = "human_review"
  update: dict[str, Any] = {"assessment": assessment, "route": route, "trail": [f"score_risk->{route}"]}
  if route == "human_review":
    update["review_kind"] = review_kind(assessment)
  return update


def _record(state: WorkflowState, outcome: str, decided_by: str, note: str) -> dict:
  return run_tool(record_decision, application_id=state["application_id"], outcome=outcome, decided_by=decided_by, note=note)


def auto_decline(state: WorkflowState) -> dict:
  result = _record(state, "declined", SYSTEM_ACTOR, "Clear policy decline (credit policy 4.07).")
  return {"decision": result.data or {}, "outcome": "declined" if result.ok else "unresolved", "trail": ["auto_decline"]}


def auto_approve(state: WorkflowState) -> dict:
  result = _record(state, "approved", SYSTEM_ACTOR, "Within the auto-approval limit; all standards met.")
  return {"decision": result.data or {}, "outcome": "approved" if result.ok else "unresolved", "trail": ["auto_approve"]}


def make_committee_node(committee: Callable[[str], Any]):
  """Advisory step before the human pause. A failure here never blocks the human review."""
  def committee_review(state: WorkflowState) -> dict:
    try:
      result = committee(state["application_id"])
      return {"committee": result.model_dump(), "trail": [f"committee:{result.outcome}"]}
    except Exception:
      logger.exception("committee step failed for %s", state["application_id"])
      return {"trail": ["committee:failed"]}
  return committee_review


def human_review(state: WorkflowState) -> dict:
  """Pause for a human. Nothing with a side effect may run here: the node starts over when the run resumes."""
  answer = interrupt(review_request(state))
  return {"human_input": answer, "trail": ["human_review"]}


def apply_human_decision(state: WorkflowState) -> dict:
  human = state.get("human_input") or {}
  result = _record(state, str(human.get("outcome", "")), str(human.get("decided_by", "")), str(human.get("note", "")))
  if result.ok:
    return {"decision": result.data, "outcome": result.data["outcome"], "review_error": None, "trail": ["apply_human_decision:ok"]}
  attempts = state.get("review_attempts", 0) + 1
  logger.warning("human decision rejected for %s: %s", state["application_id"], result.error.message)
  return {"review_error": result.error.message, "review_attempts": attempts, "trail": ["apply_human_decision:rejected"]}


def after_scoring(state: WorkflowState) -> str:
  if state.get("outcome"):
    return END
  return state["route"]


def after_human_decision(state: WorkflowState) -> str:
  if state.get("outcome"):
    return END
  if state.get("review_attempts", 0) >= get_settings().max_approval_attempts:
    return "give_up"
  return "human_review"


def give_up(state: WorkflowState) -> dict:
  return {"outcome": "unresolved", "trail": ["escalated_unresolved"]}


def after_intake(state: WorkflowState) -> str:
  return END if state.get("outcome") else "verify_documents"


def build_graph(checkpointer: Any, committee: Optional[Callable[[str], Any]] = None):
  builder = StateGraph(WorkflowState)
  builder.add_node("intake", intake)
  builder.add_node("verify_documents", verify)
  builder.add_node("score_risk", score)
  builder.add_node("auto_decline", auto_decline)
  builder.add_node("auto_approve", auto_approve)
  builder.add_node("human_review", human_review)
  if committee is not None:
    builder.add_node("committee_review", make_committee_node(committee))
    builder.add_edge("committee_review", "human_review")
  builder.add_node("apply_human_decision", apply_human_decision)
  builder.add_node("give_up", give_up)

  builder.add_edge(START, "intake")
  builder.add_conditional_edges("intake", after_intake, {"verify_documents": "verify_documents", END: END})
  builder.add_edge("verify_documents", "score_risk")
  builder.add_conditional_edges("score_risk", after_scoring, {"auto_decline": "auto_decline", "auto_approve": "auto_approve", "human_review": "committee_review" if committee is not None else "human_review", END: END})
  builder.add_edge("auto_decline", END)
  builder.add_edge("auto_approve", END)
  builder.add_edge("human_review", "apply_human_decision")
  builder.add_conditional_edges("apply_human_decision", after_human_decision, {"human_review": "human_review", "give_up": "give_up", END: END})
  builder.add_edge("give_up", END)
  return builder.compile(checkpointer=checkpointer)


def _config(application_id: str) -> dict:
  return {"configurable": {"thread_id": application_id}}


def start(graph: Any, application_id: str) -> dict:
  """Run an application until it finishes or pauses for a human. Returns {'status': 'done'|'waiting', ...}."""
  return _summarise(graph, graph.invoke({"application_id": application_id}, _config(application_id)), application_id)


def resume(graph: Any, application_id: str, human_input: dict) -> dict:
  """Continue a paused application with the reviewer's answer."""
  return _summarise(graph, graph.invoke(Command(resume=human_input), _config(application_id)), application_id)


def is_waiting(graph: Any, application_id: str) -> bool:
  return bool(graph.get_state(_config(application_id)).next)


def _summarise(graph: Any, result: dict, application_id: str) -> dict:
  pending = result.get("__interrupt__")
  if pending:
    return {"status": "waiting", "request": pending[0].value, "trail": result.get("trail", [])}
  return {"status": "done", "outcome": result.get("outcome"), "decision": result.get("decision"), "trail": result.get("trail", [])}

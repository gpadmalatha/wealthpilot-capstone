"""Workflow steps that use long-term memory (M3): recall before scoring, remember after the outcome.

Memory is namespaced by applicant_id, which comes from the validated application, never from a model.
Rule: memory may only make the workflow MORE careful. It can send a case to a human; it can never approve,
decline or relax a policy check. Memory is best-effort: a failure here is logged and never blocks a decision.
"""
import logging
from typing import Any, Callable, Optional

from capstone.memory.long_term import MemoryStore
from capstone.schemas.intake import LoanApplication
from capstone.schemas.state import WorkflowState

logger = logging.getLogger(__name__)

# Procedures an analyst can save (with remember_procedure) that send every case for this applicant to a human.
HOLD_PROCEDURES = ("always_human_review",)
# Facts the workflow writes itself after an outcome.
HOLD_FACTS = ("fraud_referral",)
RECALLED_FACTS, RECALLED_PROCEDURES, RECALLED_EVENTS = 20, 10, 5
EMPTY: dict[str, list] = {"facts": [], "procedures": [], "events": []}


def _slim(records: list[dict]) -> list[dict]:
  return [{"key": r["key"], "content": r["content"], "created_at": r["created_at"], "session_id": r["session_id"]} for r in records]


def memory_hold(memory: Optional[dict]) -> Optional[str]:
  """Why remembered context requires a human, or None."""
  if not memory:
    return None
  for procedure in memory.get("procedures", []):
    if procedure["key"] in HOLD_PROCEDURES:
      return f"standing procedure '{procedure['key']}': {procedure['content']}"
  for fact in memory.get("facts", []):
    if fact["key"] in HOLD_FACTS:
      return f"earlier fraud referral on file ({fact['content']})"
  return None


def make_recall_node(store: MemoryStore) -> Callable[[WorkflowState], dict]:
  def recall_memory(state: WorkflowState) -> dict:
    applicant_id = LoanApplication.model_validate(state["application"]).applicant_id
    try:
      memory = {
          "facts": _slim(store.recall(applicant_id, "semantic", None, RECALLED_FACTS)),
          "procedures": _slim(store.recall(applicant_id, "procedural", None, RECALLED_PROCEDURES)),
          "events": _slim(store.recall(applicant_id, "episodic", None, RECALLED_EVENTS)),
      }
    except Exception:
      logger.exception("memory recall failed for %s", applicant_id)
      return {"memory": EMPTY, "trail": ["recall_memory:failed"]}
    count = sum(len(items) for items in memory.values())
    return {"memory": memory, "trail": [f"recall_memory({count})"]}
  return recall_memory


def make_remember_node(store: MemoryStore) -> Callable[[WorkflowState], dict]:
  def remember_outcome(state: WorkflowState) -> dict:
    application = LoanApplication.model_validate(state["application"])
    assessment: dict[str, Any] = state.get("assessment") or {}
    decision = state.get("decision") or {}
    outcome = state.get("outcome")
    summary = (
        f"Application {application.application_id}: outcome={outcome}; decided_by={decision.get('decided_by', '-')}; "
        f"grade={assessment.get('grade')}; reasons={','.join(assessment.get('reason_codes', [])) or '-'}; "
        f"bureau={state.get('bureau_source')}; route={state.get('route', '-')}"
    )
    try:
      store.add_event(application.applicant_id, application.application_id, summary)
      store.save_fact(application.applicant_id, "last_outcome", f"{outcome} ({application.application_id})", application.application_id)
      if outcome == "referred_to_siu":
        store.save_fact(application.applicant_id, "fraud_referral", application.application_id, application.application_id)
    except Exception:
      logger.exception("memory write failed for %s", application.application_id)
      return {"trail": ["remember_outcome:failed"]}
    return {"trail": ["remember_outcome"]}
  return remember_outcome

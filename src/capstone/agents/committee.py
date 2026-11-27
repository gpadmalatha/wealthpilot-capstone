"""Credit committee as a LangGraph team: an actor-critic loop with enforced agent boundaries.

Topology (actor-critic with a supervisor that decides, in code, whether to loop back):

    START -> evidence_collector -> analyst -> policy_guard -> risk_reviewer -> compliance_reviewer -> supervisor
                                      ^                                                                  |
                                      +---------------------- revise (round < max_committee_rounds) -----+
                                                                                                         -> END

Why more than one agent: the memo writer (Analyst) must not mark its own work. Two critics read different slices of the
evidence with different checklists (credit risk vs fair-lending and process), and a deterministic guard that no model can
talk around sits beside them. The Evidence Collector is the only role with tools (the MCP bureau and bank tools and the
policy resource). The committee only ADVISES: it never records a decision. A human signs off afterwards in the workflow.

Boundaries, enforced in code (tests/unit/test_committee.py):
  * AGENT_TOOLS: which MCP tools each agent may call (the three model roles have none);
  * slice_for(): the slice of evidence each model role is shown;
  * AGENT_WRITES: the state keys each node may write (anything else raises PermissionError).
"""
import functools
import json
import logging
import operator
import re
from typing import Annotated, Any, Callable, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ValidationError

from capstone.agents.underwriting_agent import load_prompt
from capstone.llm.client import chat
from capstone.mcp.client import call_tools_sync, read_resource_sync
from capstone.mcp.server import POLICY_RESOURCE
from capstone.observability.tracing import span
from capstone.schemas.committee import AnalystMemo, CommitteeResult, ReviewVerdict
from capstone.settings import get_settings
from capstone.tools.policy_engine import assess_application, verify_documents

logger = logging.getLogger(__name__)

LlmFn = Callable[[list[dict]], str]
FetchFn = Callable[[str], dict]

# Words that must never appear in a memo: protected characteristics and common proxies.
PROHIBITED_TERMS = ("religion", "caste", "community", "gender", "ethnic", "race", "language", "pincode", "nationality", "marital")

# --- agent boundaries -------------------------------------------------------------------------------------------
AGENT_TOOLS = {
    "evidence_collector": ("get_bureau_report", "get_bank_statements", "check_bureau_policy"),
    "analyst": (), "risk_reviewer": (), "compliance_reviewer": (),
}
AGENT_RESOURCES = {"evidence_collector": (POLICY_RESOURCE,)}
AGENT_WRITES = {
    "evidence_collector": {"evidence"},
    "analyst": {"memo", "round"},
    "policy_guard": {"guard_verdict"},
    "risk_reviewer": {"risk_verdict"},
    "compliance_reviewer": {"compliance_verdict"},
    "supervisor": {"feedback", "verdict_log", "outcome", "final_recommendation"},
}
RISK_KEYS = ("application_id", "policy", "bureau", "bank_summary")
COMPLIANCE_KEYS = ("application_id", "policy", "documents", "bureau_policy", "policy_limits")


def slice_for(role: str, evidence: dict) -> dict:
  """The part of the evidence a role may see. The Analyst sees all of it; each reviewer sees only what its checklist needs."""
  if role == "analyst":
    return evidence
  keys = {"risk_reviewer": RISK_KEYS, "compliance_reviewer": COMPLIANCE_KEYS}[role]
  return {key: evidence.get(key) for key in keys}


def call_agent_tools(agent: str, calls: list[tuple[str, dict]]):
  """MCP tool calls on behalf of one agent. A tool outside the agent's own list is refused."""
  not_allowed = [name for name, _ in calls if name not in AGENT_TOOLS.get(agent, ())]
  if not_allowed:
    raise PermissionError(f"agent '{agent}' may not call {not_allowed}")
  return call_tools_sync(calls)


def read_agent_resource(agent: str, uri: str) -> str:
  if uri not in AGENT_RESOURCES.get(agent, ()):
    raise PermissionError(f"agent '{agent}' may not read {uri}")
  return read_resource_sync(uri)


def _owned(agent: str):
  """Decorator for a graph node: it may only write the state keys listed for this agent."""
  def decorate(node: Callable[[dict], dict]) -> Callable[[dict], dict]:
    @functools.wraps(node)
    def wrapper(state: dict) -> dict:
      with span(f"agent:{agent}", kind="agent"):
        update = node(state)
      extra = set(update) - AGENT_WRITES[agent]
      if extra:
        raise PermissionError(f"agent '{agent}' tried to write {sorted(extra)}")
      return update
    return wrapper
  return decorate


class CommitteeState(TypedDict, total=False):
  application_id: str
  evidence: dict
  memo: dict  # overwritten each round
  round: int  # control field the router reads
  guard_verdict: dict
  risk_verdict: dict
  compliance_verdict: dict
  feedback: list[str]  # reviewer issues handed to the Analyst for the next round
  verdict_log: Annotated[list[dict], operator.add]  # audit trail: appended every round
  outcome: str  # empty while the loop continues
  final_recommendation: str


def _default_llm(messages: list[dict]) -> str:
  return chat(messages, json_mode=True)


def fetch_external_via_mcp(applicant_id: str) -> dict:
  """Bureau and bank data come through the MCP server (tools), and the policy limits through its resource."""
  bureau, statements, policy = call_agent_tools("evidence_collector", [
      ("get_bureau_report", {"applicant_id": applicant_id}),
      ("get_bank_statements", {"applicant_id": applicant_id, "months": 6}),
      ("check_bureau_policy", {"applicant_id": applicant_id}),
  ])
  limits = json.loads(read_agent_resource("evidence_collector", POLICY_RESOURCE))
  return {"bureau": bureau.data, "bank": statements.data, "bureau_policy": policy.data, "policy_limits": limits}


def build_evidence(application_id: str, fetch: Optional[FetchFn] = None) -> dict:
  """Facts the committee sees. Contains no name or other identity field by design."""
  assessment = assess_application(application_id)
  external = (fetch or fetch_external_via_mcp)(assessment["applicant_id"])
  bank = external.get("bank") or {}
  months = bank.get("statements", [])
  return {
      "application_id": application_id,
      "policy": assessment,
      "documents": verify_documents(application_id),
      "bureau": external.get("bureau"),
      "bureau_policy": external.get("bureau_policy"),
      "policy_limits": external.get("policy_limits"),
      "bank_summary": {
          "months_returned": bank.get("months_returned"),
          "shortfall_months": bank.get("shortfall_months"),
          "bounced_instruments_total": sum(m["bounced_instruments"] for m in months),
          "lowest_closing_balance_inr": min((m["closing_balance_inr"] for m in months), default=None),
      },
  }


def _ask_json(system_prompt: str, user_payload: dict, model: type[BaseModel], llm: LlmFn) -> BaseModel:
  """Call the model and validate its JSON, with a bounded number of repair attempts."""
  messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": json.dumps(user_payload, default=str)}]
  last_error = ""
  for _ in range(get_settings().max_repair_attempts):
    with span(f"committee.{model.__name__}", kind="agent"):
      raw = llm(messages)
    try:
      return model.model_validate_json(raw)
    except (ValidationError, ValueError) as error:
      last_error = str(error)[:300]
      messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": f"That was not valid. Reply with the JSON only. Problem: {last_error}"}]
  raise ValueError(f"Model did not return valid JSON: {last_error}")


def policy_guard(memo: AnalystMemo, evidence: dict, round_number: int) -> ReviewVerdict:
  """Deterministic critic: policy facts and fair-lending words are checked in code."""
  policy = evidence["policy"]
  issues: list[str] = []
  if memo.recommendation == "approve" and (policy["status"] == "declined" or "FRAUD_HOLD" in policy["reason_codes"]):
    issues.append(f"Policy status is {policy['status']} with reasons {policy['reason_codes']}; the memo may not recommend approval.")
  if "FRAUD_HOLD" in policy["reason_codes"] and memo.recommendation != "refer":
    issues.append("A fraud hold must be referred to the Special Investigation Unit; the committee may only recommend 'refer'.")
  text = " ".join([memo.rationale, *memo.key_facts, *memo.conditions]).lower()
  found = sorted({term for term in PROHIBITED_TERMS if re.search(rf"\b{term}", text)})
  if found:
    issues.append(f"Memo mentions prohibited basis terms: {', '.join(found)}.")
  if not issues:
    return ReviewVerdict(reviewer="policy_guard", verdict="accept")
  # First offence: ask for a rewrite. A repeat after feedback is rejected outright.
  return ReviewVerdict(reviewer="policy_guard", verdict="revise" if round_number == 1 else "reject", issues=issues)


def build_committee_graph(llm: LlmFn, fetch: Optional[FetchFn] = None, checkpointer: Any = None):
  """Compile the committee team. Routing is a pure function of state; every role's output is validated before it is used."""
  settings = get_settings()
  analyst_prompt = load_prompt("analyst.md")
  prompts = {"risk_reviewer": load_prompt("risk_reviewer.md"), "compliance_reviewer": load_prompt("compliance_reviewer.md")}

  @_owned("evidence_collector")
  def evidence_collector(state: CommitteeState) -> dict:
    return {"evidence": build_evidence(state["application_id"], fetch)}

  @_owned("analyst")
  def analyst(state: CommitteeState) -> dict:
    memo = _ask_json(analyst_prompt, {"evidence": slice_for("analyst", state["evidence"]), "reviewer_feedback": state.get("feedback", [])}, AnalystMemo, llm)
    return {"memo": memo.model_dump(), "round": state.get("round", 0) + 1}

  @_owned("policy_guard")
  def guard(state: CommitteeState) -> dict:
    return {"guard_verdict": policy_guard(AnalystMemo(**state["memo"]), state["evidence"], state["round"]).model_dump()}

  def reviewer(role: str, key: str):
    @_owned(role)
    def review(state: CommitteeState) -> dict:
      verdict = _ask_json(prompts[role], {"evidence": slice_for(role, state["evidence"]), "memo": state["memo"]}, ReviewVerdict, llm)
      return {key: verdict.model_copy(update={"reviewer": role}).model_dump()}
    return review

  @_owned("supervisor")
  def supervisor(state: CommitteeState) -> dict:
    """Decide in code whether the committee is done. No model is involved."""
    verdicts = [ReviewVerdict(**state[key]) for key in ("guard_verdict", "risk_verdict", "compliance_verdict")]
    entry = {"round": state["round"], "memo": state["memo"], "verdicts": [v.model_dump() for v in verdicts]}
    kinds = {v.verdict for v in verdicts}
    update: dict = {"verdict_log": [entry], "outcome": "", "feedback": []}
    if "escalate" in kinds:
      update.update(outcome="escalated", final_recommendation="refer")
    elif "reject" in kinds:
      update.update(outcome="rejected", final_recommendation="refer")
    elif kinds == {"accept"}:
      update.update(outcome="agreed", final_recommendation=state["memo"]["recommendation"])
    elif state["round"] >= settings.max_committee_rounds:
      update.update(outcome="exhausted", final_recommendation="refer")  # round budget spent: a human takes over
    else:
      update["feedback"] = [f"{v.reviewer}: {issue}" for v in verdicts if v.verdict == "revise" for issue in v.issues]
    return update

  def route(state: CommitteeState) -> str:
    """Conditional edge: a pure function of state."""
    return END if state.get("outcome") else "analyst"

  builder = StateGraph(CommitteeState)
  nodes = {"evidence_collector": evidence_collector, "analyst": analyst, "policy_guard": guard,
           "risk_reviewer": reviewer("risk_reviewer", "risk_verdict"), "compliance_reviewer": reviewer("compliance_reviewer", "compliance_verdict"),
           "supervisor": supervisor}
  for name, node in nodes.items():
    builder.add_node(name, node)
  builder.add_edge(START, "evidence_collector")
  for before, after in [("evidence_collector", "analyst"), ("analyst", "policy_guard"), ("policy_guard", "risk_reviewer"),
                        ("risk_reviewer", "compliance_reviewer"), ("compliance_reviewer", "supervisor")]:
    builder.add_edge(before, after)
  builder.add_conditional_edges("supervisor", route, {"analyst": "analyst", END: END})
  return builder.compile(checkpointer=checkpointer)


def run_committee(application_id: str, *, llm: Optional[LlmFn] = None, fetch: Optional[FetchFn] = None,
                  checkpointer: Any = None, thread_id: Optional[str] = None) -> CommitteeResult:
  """Run the committee graph to its end. Any failure (model, MCP) returns 'unavailable': nothing is decided and a human reviews."""
  graph = build_committee_graph(llm or _default_llm, fetch, checkpointer)
  settings = get_settings()
  config: dict = {"recursion_limit": 8 * settings.max_committee_rounds + 12}  # explicit cap on top of the round counter
  if checkpointer is not None:
    config["configurable"] = {"thread_id": thread_id or f"committee-{application_id}"}
  last: dict = {}
  try:
    for last in graph.stream({"application_id": application_id, "round": 0, "verdict_log": []}, config, stream_mode="values"):
      pass
  except Exception as error:  # a model or MCP failure must not decide anything; the human still reviews
    logger.warning("committee unavailable for %s: %s", application_id, error)
    memo = AnalystMemo(**last["memo"]) if last.get("memo") else None
    return CommitteeResult(outcome="unavailable", final_recommendation="refer", rounds=len(last.get("verdict_log", [])), memo=memo, verdict_log=last.get("verdict_log", []))
  return CommitteeResult(outcome=last["outcome"], final_recommendation=last["final_recommendation"], rounds=last["round"],
                         memo=AnalystMemo(**last["memo"]), verdict_log=last["verdict_log"])

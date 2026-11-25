"""Committee of three roles with a bounded actor-critic loop.

Analyst (actor) drafts a memo. Risk Reviewer and Compliance Reviewer (critics) check it, plus a deterministic
policy guard that no model can talk around. A reviewer may accept, ask for a revision, reject, or escalate.
The loop runs at most max_committee_rounds times. The committee only ADVISES: it never records a decision.
"""
import json
import logging
import re
from typing import Callable, Optional

from pydantic import BaseModel, ValidationError

from capstone.agents.underwriting_agent import load_prompt
from capstone.llm.client import chat
from capstone.mcp.client import call_tools_sync
from capstone.schemas.committee import AnalystMemo, CommitteeResult, ReviewVerdict
from capstone.settings import get_settings
from capstone.tools.policy_engine import assess_application, verify_documents

logger = logging.getLogger(__name__)

LlmFn = Callable[[list[dict]], str]
FetchFn = Callable[[str], dict]

# Words that must never appear in a memo: protected characteristics and common proxies.
PROHIBITED_TERMS = ("religion", "caste", "community", "gender", "ethnic", "race", "language", "pincode", "nationality", "marital")


def _default_llm(messages: list[dict]) -> str:
  return chat(messages, json_mode=True)


def fetch_external_via_mcp(applicant_id: str) -> dict:
  """Bureau and bank data come through the MCP server, not by importing the mock tables."""
  bureau, statements, policy = call_tools_sync([
      ("get_bureau_report", {"applicant_id": applicant_id}),
      ("get_bank_statements", {"applicant_id": applicant_id, "months": 6}),
      ("check_bureau_policy", {"applicant_id": applicant_id}),
  ])
  return {"bureau": bureau.data, "bank": statements.data, "bureau_policy": policy.data}


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


def run_committee(application_id: str, *, llm: Optional[LlmFn] = None, fetch: Optional[FetchFn] = None) -> CommitteeResult:
  llm = llm or _default_llm
  settings = get_settings()
  evidence = build_evidence(application_id, fetch)
  analyst_prompt = load_prompt("analyst.md")
  reviewers = [("risk_reviewer", load_prompt("risk_reviewer.md")), ("compliance_reviewer", load_prompt("compliance_reviewer.md"))]
  feedback: list[str] = []
  log: list[dict] = []
  memo: Optional[AnalystMemo] = None

  try:
    for round_number in range(1, settings.max_committee_rounds + 1):
      memo = _ask_json(analyst_prompt, {"evidence": evidence, "reviewer_feedback": feedback}, AnalystMemo, llm)
      verdicts = [policy_guard(memo, evidence, round_number)]
      for name, prompt in reviewers:
        verdict = _ask_json(prompt, {"evidence": evidence, "memo": memo.model_dump()}, ReviewVerdict, llm)
        verdicts.append(verdict.model_copy(update={"reviewer": name}))
      log.append({"round": round_number, "memo": memo.model_dump(), "verdicts": [v.model_dump() for v in verdicts]})

      kinds = {v.verdict for v in verdicts}
      if "escalate" in kinds:
        return CommitteeResult(outcome="escalated", final_recommendation="refer", rounds=round_number, memo=memo, verdict_log=log)
      if "reject" in kinds:
        return CommitteeResult(outcome="rejected", final_recommendation="refer", rounds=round_number, memo=memo, verdict_log=log)
      if kinds == {"accept"}:
        return CommitteeResult(outcome="agreed", final_recommendation=memo.recommendation, rounds=round_number, memo=memo, verdict_log=log)
      feedback = [f"{v.reviewer}: {issue}" for v in verdicts if v.verdict == "revise" for issue in v.issues]
  except Exception as error:  # a model or MCP failure must not decide anything; the human still reviews
    logger.warning("committee unavailable for %s: %s", application_id, error)
    return CommitteeResult(outcome="unavailable", final_recommendation="refer", rounds=len(log), memo=memo, verdict_log=log)

  return CommitteeResult(outcome="exhausted", final_recommendation="refer", rounds=len(log), memo=memo, verdict_log=log)

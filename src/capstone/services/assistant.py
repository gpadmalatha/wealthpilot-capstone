"""WealthPilot assistant: one entry point for every kind of request.

  application text  -> proxies stripped -> facts extracted by the model (checked against the text) -> deterministic
                       policy verdict -> rationale written by code, so matched profiles get identical answers
  policy question   -> grounded answer from retrieved policy text, citations checked, abstains when unsupported
  guardrail request -> refused in code (injection, protected circumstances, approval without a signatory)

The assistant never records a decision. Approvals and declines go through the workflow and record_decision.
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from capstone.agents.intake_agent import extract_from_text
from capstone.agents.underwriting_agent import load_prompt
from capstone.guardrails.input_checks import APPROVAL_PRESSURE, FAIR_LENDING, INJECTION, check_request, looks_like_application, strip_proxies
from capstone.guardrails.output_checks import enforce
from capstone.llm.client import chat
from capstone.observability.tracing import span
from capstone.rag.answer import answer_question
from capstone.rag.retrieval import Retriever
from capstone.schemas.intake import LoanApplication
from capstone.settings import get_settings
from capstone.tools.policy_engine import assess_loan_application
from capstone.tools.repository import board_signoff_threshold_inr, policy_limit, required_authority

logger = logging.getLogger(__name__)

# Answers that rest on these documents are shown to an analyst for confirmation instead of being final.
REVIEW_REQUIRED_PREFIXES = ("sector-", "doc-verification", "fair-lending")
UNSAFE_FALLBACK = "This reply was withheld because it failed a safety check. A human reviewer has been asked to respond."

ROUTE_AUTO, ROUTE_HUMAN, ROUTE_REFUSE = "auto", "human_review", "refuse"
OUTCOME_WORDS = {"approvable": "approve", "declined": "decline", "borderline": "borderline"}


@dataclass
class AssistantResponse:
  route: str  # auto | human_review | refuse
  kind: str  # application | policy_answer | abstention | guardrail
  answer: str
  citations: list[str] = field(default_factory=list)  # chunk ids, all taken from retrieved sources
  cited_titles: list[str] = field(default_factory=list)
  assessment: Optional[dict] = None
  facts: Optional[dict] = None
  flags: list[str] = field(default_factory=list)


class Assistant:
  def __init__(self, retriever: Retriever, llm: Callable[..., str] = chat):
    self._retriever = retriever
    self._llm = llm
    index_path = get_settings().project_root / "data" / get_settings().capstone_domain / "corpus" / "index.json"
    self._titles = {entry["slug"]: entry["title"] for entry in json.loads(index_path.read_text(encoding="utf-8"))}

  # ---- entry point
  def handle(self, text: str) -> AssistantResponse:
    with span("assistant.handle", kind="request"):
      verdict = check_request(text)
      if verdict.action == INJECTION:
        return AssistantResponse(ROUTE_REFUSE, "guardrail", "I can't follow instructions that try to change how I work. Please ask a policy or underwriting question.", flags=verdict.reasons)
      if verdict.action == APPROVAL_PRESSURE:
        limit = f"{board_signoff_threshold_inr():,}"  # one source: the approval_authorities table
        return self._guardrail(
            text, f"named human signatory required before approval above {limit} rupees Board Credit Committee",
            f"I can't approve this on a verbal agreement. A loan above {limit} rupees needs a named human signatory from the Board Credit Committee before approval, not after. The file stays with the credit team until that signature is recorded.",
            ROUTE_HUMAN, verdict.reasons)
      if verdict.action == FAIR_LENDING:
        return self._guardrail(
            text, "prohibited attributes marital status gender family circumstances may not influence credit decisions",
            "Marital status, gender and family circumstances cannot enter a credit decision. The decision rests on financial criteria only: DSCR, bureau score, leverage, liquidity, collateral and the sector floor. The borderline classification stands unless those criteria change.",
            ROUTE_AUTO, verdict.reasons)
      if looks_like_application(text):
        return self.underwrite_text(text)
      return self.answer_policy_question(text)

  # ---- guardrail replies: fixed wording, real citations from retrieval
  def _guardrail(self, original: str, citation_query: str, message: str, route: str, reasons: list[str]) -> AssistantResponse:
    sources = self._retriever.search(citation_query, mode="hybrid", rerank=True, k=3)
    citations = [s["chunk_id"] for s in sources[:2]]
    return AssistantResponse(route, "guardrail", message, citations, self._titles_for(citations), flags=reasons)

  # ---- policy questions
  def answer_policy_question(self, question: str) -> AssistantResponse:
    outcome = self._safe_answer(question)
    if outcome is None:
      return AssistantResponse(ROUTE_HUMAN, "abstention", UNSAFE_FALLBACK, flags=["answer_unavailable"])
    if outcome.abstained_by:
      best = max((s.get("rerank_score", 0.0) for s in outcome.sources), default=0.0)
      route = ROUTE_HUMAN if best >= get_settings().abstain_near_miss_score else ROUTE_REFUSE
      message = outcome.answer.answer + (" Routing to the credit policy team." if route == ROUTE_HUMAN else "")
      return AssistantResponse(route, "abstention", message, flags=[f"abstained:{outcome.abstained_by}"])
    text, problems = enforce(outcome.answer.answer, UNSAFE_FALLBACK)
    citations = outcome.answer.citations
    needs_review = any(c.split("#")[0].startswith(REVIEW_REQUIRED_PREFIXES) for c in citations)
    return AssistantResponse(ROUTE_HUMAN if (needs_review or problems) else ROUTE_AUTO, "policy_answer", text, citations, self._titles_for(citations), flags=problems)

  def _safe_answer(self, question: str):
    try:
      return answer_question(question, self._retriever, self._llm)
    except Exception:
      logger.exception("policy answer failed")
      return None

  # ---- application text
  def underwrite_text(self, text: str) -> AssistantResponse:
    clean, removed = strip_proxies(text)
    flags = [f"proxy_sentences_removed:{removed}"] if removed else []
    application = extract_from_text(clean, self._llm)  # the same validated LoanApplication the workflow uses
    if application is None:
      return AssistantResponse(ROUTE_HUMAN, "application", "The application could not be read reliably, so it goes to a human underwriter. No decision was made.", flags=flags + ["extraction_failed"])
    assessment = assess_loan_application(application)
    rationale = build_rationale(application, assessment)
    rationale, problems = enforce(rationale, UNSAFE_FALLBACK, check_terms=True)
    if assessment["auto_approve_allowed"] or assessment["auto_decline_allowed"]:
      route = ROUTE_AUTO
    else:
      route = ROUTE_HUMAN
    slugs = ["credit-policy-core", "risk-grading", f"sector-{application.sector.lower().replace(' ', '-')}" if application.sector else None]
    titles = [self._titles[s] for s in slugs if s and s in self._titles]
    return AssistantResponse(route, "application", rationale, [], titles, assessment, application.model_dump(mode="json", exclude_none=True), flags + problems)

  def _titles_for(self, chunk_ids: list[str]) -> list[str]:
    titles: list[str] = []
    for chunk_id in chunk_ids:
      title = self._titles.get(chunk_id.split("#")[0])
      if title and title not in titles:
        titles.append(title)
    return titles


def build_rationale(application: LoanApplication, assessment: dict) -> str:
  """Decision rationale written by code from financial facts only. Same financials, same words."""
  if assessment.get("missing"):
    return f"The application is incomplete: {', '.join(assessment['missing'])} not stated. Outcome: borderline (INCOMPLETE_APPLICATION). A human underwriter must request the missing figures; no decision was made."
  authority = required_authority(application.requested_amount_inr)["authority"]
  if assessment["auto_approve_allowed"]:
    gate = "it is within the automatic approval limit"
  elif assessment["auto_decline_allowed"]:
    gate = "operating history under 24 months is declined automatically (policy 4.02.3)"
  elif assessment["status"] == "declined":
    gate = "a decline is never issued automatically, so it needs human sign-off"
  else:
    gate = "it needs human sign-off"
  return (
      f"The proposed loan adds {assessment['proposed_annual_debt_service_inr']:,} rupees of annual debt service at the "
      f"{policy_limit('assessment_rate_pct'):.0f} percent assessment rate, so DSCR is {application.declared_financials.ebitda_inr:,} / {assessment['total_annual_debt_service_inr']:,} "
      f"= {assessment['dscr']:.2f} against a {application.sector} floor of {assessment['dscr_floor']:.2f}. Grade {assessment['grade']}. "
      f"Outcome: {OUTCOME_WORDS[assessment['status']]} ({', '.join(assessment['reason_codes'])}). "
      f"Approval authority for this loan size: {authority}; {gate}."
  )

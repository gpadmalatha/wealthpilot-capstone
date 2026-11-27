"""Grounded answers: only retrieved chunks, citations checked in code, abstention when unsupported."""
import json
import logging
from dataclasses import dataclass
from typing import Callable, Optional

from pydantic import BaseModel, ValidationError, model_validator

from capstone.guardrails.input_checks import contains_injection
from capstone.llm.client import chat
from capstone.observability.tracing import annotate
from capstone.rag.retrieval import Retriever
from capstone.settings import get_settings

logger = logging.getLogger(__name__)

ABSTAIN_TEXT = "The policy documents provided do not contain an answer to this question."


def drop_injected_chunks(sources: list[dict]) -> tuple[list[dict], list[str]]:
  """Input scan on retrieved content: a chunk that tries to give the model orders is dropped before the prompt is built."""
  clean = [s for s in sources if not contains_injection(s["text"])]
  flagged = [s["chunk_id"] for s in sources if contains_injection(s["text"])]
  if flagged:
    logger.warning("dropped retrieved chunks that contain instructions: %s", flagged)
    annotate(retrieved_injection_flagged=",".join(flagged))
  return clean, flagged


class AnswerError(Exception):
  """The model kept citing sources that were not retrieved, or returned invalid JSON."""


class GroundedAnswer(BaseModel):
  answer: str
  citations: list[str]
  grounded: bool

  @model_validator(mode="after")
  def citations_match_grounding(self) -> "GroundedAnswer":
    if self.grounded and not self.citations:
      raise ValueError("a grounded answer must cite at least one source")
    if not self.grounded and self.citations:
      raise ValueError("an answer that is not grounded must not cite anything")
    return self


@dataclass
class AnswerOutcome:
  answer: GroundedAnswer
  sources: list[dict]
  abstained_by: Optional[str]  # None, "low_relevance" or "retrieved_content_flagged" (code), or "model"


def _load_prompt() -> str:
  return (get_settings().project_root / "prompts" / "answer.md").read_text(encoding="utf-8")


def _format_sources(sources: list[dict]) -> str:
  return "\n\n".join(
      f'<source id="{s["chunk_id"]}" title="{s["title"]}" section="{s["heading"]}">\n{s["text"]}\n</source>' for s in sources
  )


def answer_question(question: str, retriever: Retriever, chat_function: Callable[..., str] = chat) -> AnswerOutcome:
  settings = get_settings()
  sources, flagged = drop_injected_chunks(retriever.search(question, mode="hybrid", rerank=True))
  if flagged and not sources:
    return AnswerOutcome(GroundedAnswer(answer=ABSTAIN_TEXT, citations=[], grounded=False), [], "retrieved_content_flagged")
  if not sources or sources[0].get("rerank_score", 10.0) < settings.rerank_min_score:
    logger.info("abstaining: best reranked source scored below %.1f", settings.rerank_min_score)
    return AnswerOutcome(GroundedAnswer(answer=ABSTAIN_TEXT, citations=[], grounded=False), sources, "low_relevance")

  allowed = {s["chunk_id"] for s in sources}
  messages = [
      {"role": "system", "content": _load_prompt()},
      {"role": "user", "content": f"Question: {question}\n\n{_format_sources(sources)}"},
  ]
  last_error = "no attempt made"
  for _ in range(settings.max_repair_attempts):
    reply = chat_function(messages, json_mode=True)
    try:
      answer = GroundedAnswer.model_validate(json.loads(reply))
      invented = [c for c in answer.citations if c not in allowed]
      if invented:
        raise ValueError(f"these citations were not among the sources provided: {invented}. Cite only: {sorted(allowed)}")
      return AnswerOutcome(answer, sources, None if answer.grounded else "model")
    except (ValueError, ValidationError) as error:
      last_error = str(error)
      messages += [{"role": "assistant", "content": reply}, {"role": "user", "content": f"Invalid: {last_error}. Return corrected JSON only."}]
  raise AnswerError(f"no valid grounded answer after {settings.max_repair_attempts} attempts: {last_error}")

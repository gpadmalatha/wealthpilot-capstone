"""LLM reranker: scores each candidate against the query and returns them in score order."""
import json
import logging
from typing import Callable

from pydantic import BaseModel, Field, ValidationError

from capstone.llm.client import chat
from capstone.settings import get_settings

logger = logging.getLogger(__name__)

PASSAGE_CHARS = 700


class RerankError(Exception):
  """The reranker could not produce valid scores within the repair limit."""


class RerankScore(BaseModel):
  id: int = Field(ge=0)
  score: float = Field(ge=0, le=10)


class RerankResult(BaseModel):
  scores: list[RerankScore]


def _load_prompt() -> str:
  return (get_settings().project_root / "prompts" / "rerank.md").read_text(encoding="utf-8")


def rerank(query: str, candidates: list[dict], chat_function: Callable[..., str] = chat) -> list[dict]:
  """Return the candidates ordered by rerank_score (highest first). Ties keep their incoming order."""
  if not candidates:
    return []
  passages = "\n\n".join(f"[{i}] {c['title']} | {c['heading']}\n{c['text'][:PASSAGE_CHARS]}" for i, c in enumerate(candidates))
  messages = [
      {"role": "system", "content": _load_prompt()},
      {"role": "user", "content": f"Question: {query}\n\nPassages:\n{passages}"},
  ]
  last_error = "no attempt made"
  for _ in range(get_settings().max_repair_attempts):
    reply = chat_function(messages, json_mode=True)
    try:
      result = RerankResult.model_validate(json.loads(reply))
      by_id = {item.id: item.score for item in result.scores}
      if set(by_id) != set(range(len(candidates))):
        raise ValueError(f"expected one score for each id 0..{len(candidates) - 1}")
      ranked = sorted(range(len(candidates)), key=lambda i: (-by_id[i], i))
      return [{**candidates[i], "rerank_score": by_id[i]} for i in ranked]
    except (ValueError, ValidationError) as error:
      last_error = str(error)
      messages += [{"role": "assistant", "content": reply}, {"role": "user", "content": f"Invalid: {last_error}. Return corrected JSON only."}]
  raise RerankError(f"reranker failed after {get_settings().max_repair_attempts} attempts: {last_error}")

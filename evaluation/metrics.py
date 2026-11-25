"""Retrieval metrics, scored at section level: 'source#section' with any .pN split suffix removed."""
import re

_SPLIT_SUFFIX = re.compile(r"\.p\d+$")


def section_key(chunk_id: str) -> str:
  return _SPLIT_SUFFIX.sub("", chunk_id)


def ranked_sections(chunk_ids: list[str]) -> list[str]:
  """Section keys in rank order, each section counted once (a split section is not penalised)."""
  seen: list[str] = []
  for chunk_id in chunk_ids:
    key = section_key(chunk_id)
    if key not in seen:
      seen.append(key)
  return seen


def precision_at_k(ranked: list[str], expected: set[str], k: int) -> float:
  top = ranked[:k]
  return sum(1 for key in top if key in expected) / k if k else 0.0


def recall_at_k(ranked: list[str], expected: set[str], k: int) -> float:
  if not expected:
    return 0.0
  return sum(1 for key in ranked[:k] if key in expected) / len(expected)


def reciprocal_rank(ranked: list[str], expected: set[str]) -> float:
  for position, key in enumerate(ranked, start=1):
    if key in expected:
      return 1.0 / position
  return 0.0

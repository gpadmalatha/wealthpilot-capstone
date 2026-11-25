"""Score a retrieval configuration on the golden set."""
import json
from pathlib import Path
from typing import Callable

from evaluation.metrics import precision_at_k, ranked_sections, recall_at_k, reciprocal_rank


def load_golden(path: Path) -> list[dict]:
  return json.loads(path.read_text(encoding="utf-8"))


def score_configuration(golden: list[dict], search: Callable[[str], list[dict]], k: int) -> dict:
  """Average precision@k, recall@k and MRR over the answerable questions (those with expected sections)."""
  rows = []
  for item in golden:
    expected = set(item["expected_sections"])
    if not expected:
      continue  # unanswerable questions are judged on abstention, not retrieval
    ranked = ranked_sections([hit["chunk_id"] for hit in search(item["question"])])
    rows.append({
        "id": item["id"],
        "precision": precision_at_k(ranked, expected, k),
        "recall": recall_at_k(ranked, expected, k),
        "rr": reciprocal_rank(ranked, expected),
        "ranked": ranked[:k],
    })
  count = len(rows)
  return {
      "questions": count,
      f"precision@{k}": round(sum(r["precision"] for r in rows) / count, 3),
      f"recall@{k}": round(sum(r["recall"] for r in rows) / count, 3),
      "MRR": round(sum(r["rr"] for r in rows) / count, 3),
      "rows": rows,
  }

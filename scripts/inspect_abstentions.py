r"""Print the best reranker score for each golden question, to choose the abstention thresholds from evidence.

Run:  python scripts\inspect_abstentions.py     (about 2 minutes; model calls)
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capstone.rag.corpus import load_policy_chunks  # noqa: E402
from capstone.rag.index import PolicyIndex  # noqa: E402
from capstone.rag.retrieval import Retriever  # noqa: E402
from capstone.settings import get_settings  # noqa: E402


def main():
  settings = get_settings()
  golden = json.loads((settings.project_root / "evaluation" / "datasets" / "final_golden.json").read_text(encoding="utf-8"))
  index = PolicyIndex()
  try:
    retriever = Retriever(index, load_policy_chunks())
    print(f"abstain below rerank_min_score={settings.rerank_min_score}; near-miss cut-off abstain_near_miss_score={settings.abstain_near_miss_score}\n")
    print(f"{'case':20s} {'category':13s} best_score  top_source")
    for case in golden:
      if case["category"] in ("bias_probe", "guardrail"):
        continue
      hits = retriever.search(case["question"], mode="hybrid", rerank=True)
      best = max(hits, key=lambda h: h.get("rerank_score", 0.0)) if hits else None
      print(f"{case['id']:20s} {case['category']:13s} {best['rerank_score'] if best else 'none':<11} {best['chunk_id'] if best else ''}")
      time.sleep(settings.eval_delay_seconds)
  finally:
    index.close()


if __name__ == "__main__":
  main()

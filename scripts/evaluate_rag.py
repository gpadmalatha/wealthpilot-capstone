"""M4 evaluation: score retrieval configurations on the golden set, then grounded answers.

Baseline = vector search only. Change = hybrid (vector + BM25, fused). A further row adds the reranker.
All rows use the same golden set (evaluation/datasets/retrieval_golden.json). Evidence: docs/m4_evaluation.txt
"""
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # evaluation/ lives at the repository root

from capstone.llm.client import embed  # noqa: E402
from capstone.rag.answer import answer_question  # noqa: E402
from capstone.rag.corpus import load_policy_chunks  # noqa: E402
from capstone.rag.index import PolicyIndex  # noqa: E402
from capstone.rag.rerank import rerank  # noqa: E402
from capstone.rag.retrieval import Retriever  # noqa: E402
from capstone.settings import get_settings  # noqa: E402
from evaluation.metrics import section_key  # noqa: E402
from evaluation.runner import load_golden, score_configuration  # noqa: E402


EVAL_K = 3  # score the top 3: with 111 chunks, the top 5 is too easy to tell configurations apart


def main() -> None:
  logging.basicConfig(level=logging.WARNING)
  settings = get_settings()
  k = EVAL_K
  golden = load_golden(settings.project_root / "evaluation" / "datasets" / "retrieval_golden.json")

  embed_cache: dict[str, list[float]] = {}
  def cached_embed(texts: list[str]) -> list[list[float]]:
    missing = [t for t in texts if t not in embed_cache]
    if missing:
      for text, vector in zip(missing, embed(missing)):
        embed_cache[text] = vector
    return [embed_cache[t] for t in texts]

  rerank_cache: dict[str, list[dict]] = {}
  def cached_rerank(query: str, candidates: list[dict]) -> list[dict]:
    if query not in rerank_cache:
      rerank_cache[query] = rerank(query, candidates)
      time.sleep(settings.eval_delay_seconds)
    return rerank_cache[query]

  index = PolicyIndex(embed_function=cached_embed)
  try:
    retriever = Retriever(index, load_policy_chunks(), rerank_function=cached_rerank)
    configs = [
        ("baseline: vector only", dict(mode="vector", rerank=False)),
        ("change: hybrid (vector + BM25, fused)", dict(mode="hybrid", rerank=False)),
        ("extra: hybrid + reranker", dict(mode="hybrid", rerank=True)),
    ]
    lines = [f"model: {settings.llm_model}", f"embedding_model: {settings.embedding_model}", f"golden questions: {len(golden)} ({sum(1 for g in golden if g['expected_sections'])} answerable, scored at k={k})", ""]
    lines.append(f"{'configuration':42s} precision@{k}  recall@{k}  MRR")
    details = []
    for name, options in configs:
      result = score_configuration(golden, lambda q, o=options: retriever.search(q, k=k, **o), k)
      lines.append(f"{name:42s} {result[f'precision@{k}']:<12} {result[f'recall@{k}']:<9} {result['MRR']}")
      details.append((name, result))
    lines += ["", "Per-question first-hit detail (expected section -> where it ranked):"]
    expected_by_id = {g["id"]: g["expected_sections"] for g in golden}
    for name, result in details:
      misses = [f"{r['id']} (got {r['ranked'][:3]})" for r in result["rows"] if r["recall"] < 1.0]
      lines.append(f"  {name}: recall<1 for {misses if misses else 'none'}")

    lines += ["", "GROUNDED ANSWERS (hybrid + reranker):"]
    grounded_ok = abstain_ok = invented = answerable = unanswerable = 0
    for item in golden:
      outcome = answer_question(item["question"], retriever)
      time.sleep(settings.eval_delay_seconds)
      answer = outcome.answer
      retrieved_ids = {s["chunk_id"] for s in outcome.sources}
      invented += sum(1 for c in answer.citations if c not in retrieved_ids)
      cited_sections = {section_key(c) for c in answer.citations}
      if item["expected_sections"]:
        answerable += 1
        facts = all(fact.lower() in answer.answer.lower() for fact in item["answer_contains"])
        cited = bool(cited_sections & set(item["expected_sections"]))
        ok = answer.grounded and facts and cited
        grounded_ok += ok
        lines.append(f"  {item['id']} {'OK  ' if ok else 'FAIL'} grounded={answer.grounded} facts={facts} cited_expected={cited} cites={sorted(cited_sections)}")
      else:
        unanswerable += 1
        ok = (not answer.grounded) and not answer.citations
        abstain_ok += ok
        lines.append(f"  {item['id']} {'OK  ' if ok else 'FAIL'} abstained={not answer.grounded} by={outcome.abstained_by} cites={sorted(cited_sections)}")
    lines += ["", f"answerable questions grounded, correct and cited: {grounded_ok}/{answerable}",
              f"unanswerable questions correctly refused: {abstain_ok}/{unanswerable}",
              f"citations outside the retrieved sources (fabricated): {invented}"]
  finally:
    index.close()
  report = settings.project_root / "docs" / "m4_evaluation.txt"
  report.write_text("\n".join(lines), encoding="utf-8")
  print("\n".join(lines))


if __name__ == "__main__":
  main()

"""Retrieval: vector, BM25, or hybrid (reciprocal-rank fusion), optionally followed by a reranker."""
import logging
from dataclasses import asdict
from typing import Callable, Literal, Optional

from capstone.rag.bm25 import BM25Index
from capstone.rag.chunking import Chunk
from capstone.rag.index import PolicyIndex
from capstone.rag.rerank import rerank as default_rerank
from capstone.settings import get_settings

logger = logging.getLogger(__name__)

Mode = Literal["vector", "bm25", "hybrid"]


def reciprocal_rank_fusion(rankings: list[list[dict]], rrf_k: int) -> list[dict]:
  """Fuse several ranked lists: each chunk scores the sum of 1 / (rrf_k + rank) over the lists it appears in."""
  scores: dict[str, float] = {}
  documents: dict[str, dict] = {}
  for ranking in rankings:
    for rank, document in enumerate(ranking, start=1):
      key = document["chunk_id"]
      scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
      documents.setdefault(key, document)
  ordered = sorted(scores, key=lambda key: (-scores[key], key))
  return [{**documents[key], "score": round(scores[key], 5)} for key in ordered]


class Retriever:
  def __init__(self, index: PolicyIndex, chunks: list[Chunk], rerank_function: Callable[[str, list[dict]], list[dict]] = default_rerank) -> None:
    self._index = index
    self._documents = [asdict(chunk) for chunk in chunks]
    self._bm25 = BM25Index(self._documents)
    self._rerank = rerank_function

  def search(self, query: str, *, mode: Mode = "hybrid", rerank: bool = False, k: Optional[int] = None) -> list[dict]:
    settings = get_settings()
    top_k = k or settings.retrieval_top_k
    candidates = settings.retrieval_candidates
    if mode == "vector":
      results = self._index.search(query, limit=candidates)
    elif mode == "bm25":
      results = self._bm25.search(query, limit=candidates)
    else:
      results = reciprocal_rank_fusion(
          [self._index.search(query, limit=candidates), self._bm25.search(query, limit=candidates)],
          settings.rrf_k,
      )
    if rerank:
      reordered = self._rerank(query, results[:settings.rerank_candidates])
      return reordered[:top_k]  # the reranker's order is the order that is used
    return results[:top_k]

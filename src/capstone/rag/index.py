"""Qdrant index over the lending-policy chunks, with source and section metadata for filtering."""
import logging
import uuid
from pathlib import Path
from typing import Callable, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

from capstone.llm.client import embed
from capstone.rag.chunking import Chunk
from capstone.rag.embeddings import embed_texts
from capstone.settings import get_settings

logger = logging.getLogger(__name__)

EmbedFunction = Callable[[list[str]], list[list[float]]]


def default_index_path() -> Path:
  folder = get_settings().project_root / "runtime" / "qdrant"
  folder.mkdir(parents=True, exist_ok=True)
  return folder


class PolicyIndex:
  """Local on-disk Qdrant collection. Reopening the same path sees what was built before."""

  def __init__(self, path: Optional[Path] = None, embed_function: EmbedFunction = embed) -> None:
    self._client = QdrantClient(path=str(path or default_index_path()))
    self._embed = embed_function
    self._collection = get_settings().qdrant_collection

  def close(self) -> None:
    self._client.close()

  def build(self, chunks: list[Chunk], pause_seconds: Optional[float] = None) -> int:
    """(Re)create the collection from chunks. Returns the number of points stored."""
    vectors = embed_texts([chunk.text for chunk in chunks], self._embed, pause_seconds)
    if self._client.collection_exists(self._collection):
      self._client.delete_collection(self._collection)
    self._client.create_collection(
        self._collection,
        vectors_config=VectorParams(size=len(vectors[0]), distance=Distance.COSINE),
    )
    points = [
        PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.chunk_id)),
            vector=vector,
            payload={
                "chunk_id": chunk.chunk_id,
                "source": chunk.source,
                "title": chunk.title,
                "section_type": chunk.section_type,
                "section_number": chunk.section_number,
                "heading": chunk.heading,
                "text": chunk.text,
            },
        )
        for chunk, vector in zip(chunks, vectors)
    ]
    self._client.upsert(self._collection, points=points)
    logger.info("indexed %d chunks", len(points))
    return len(points)

  def count(self) -> int:
    if not self._client.collection_exists(self._collection):
      return 0
    return self._client.count(self._collection).count

  def search(
      self,
      query: str,
      *,
      source: Optional[str] = None,
      section_type: Optional[str] = None,
      limit: int = 5,
  ) -> list[dict]:
    """Nearest chunks to the query, optionally restricted by source or section_type metadata."""
    conditions = []
    if source:
      conditions.append(FieldCondition(key="source", match=MatchValue(value=source)))
    if section_type:
      conditions.append(FieldCondition(key="section_type", match=MatchValue(value=section_type)))
    vector = self._embed([query])[0]
    result = self._client.query_points(
        self._collection,
        query=vector,
        query_filter=Filter(must=conditions) if conditions else None,
        limit=limit,
        with_payload=True,
    )
    return [{"score": round(point.score, 4), **point.payload} for point in result.points]

"""Offline tests for chunking and the Qdrant index (fake embeddings, no model calls)."""
import hashlib

import pytest

from capstone.rag.chunking import chunk_policy
from capstone.rag.corpus import load_policy_chunks
from capstone.rag.index import PolicyIndex

DIMENSIONS = 64


def fake_embed(texts):
  """Deterministic bag-of-words vectors: shared words give similar vectors."""
  vectors = []
  for text in texts:
    vector = [0.0] * DIMENSIONS
    for word in text.lower().split():
      bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % DIMENSIONS
      vector[bucket] += 1.0
    vectors.append(vector)
  return vectors


@pytest.fixture(scope="module")
def chunks():
  return load_policy_chunks()


def test_every_chunk_carries_source_and_section_metadata(chunks):
  assert len(chunks) > 60
  for chunk in chunks:
    assert chunk.source and chunk.title and chunk.section_type and chunk.heading and chunk.chunk_id


def test_chunk_ids_are_unique(chunks):
  ids = [chunk.chunk_id for chunk in chunks]
  assert len(ids) == len(set(ids))


def test_all_heading_styles_are_split(chunks):
  by_source: dict[str, int] = {}
  for chunk in chunks:
    by_source[chunk.source] = by_source.get(chunk.source, 0) + 1
  assert by_source["sector-food-processing"] >= 6  # bold-number headings
  assert by_source["sector-it-services"] >= 6      # #### headings
  assert by_source["sector-textiles"] >= 6         # ### headings


def test_long_section_is_split_on_paragraphs_not_mid_sentence():
  text = "# Doc\n\n### 1.1 Rule\n" + "\n\n".join(f"Paragraph {i}. " + "word " * 40 for i in range(6))
  pieces = chunk_policy("doc", "Doc", "policy", text, max_chars=500)
  assert len(pieces) > 1 and all(len(p.text) < 700 for p in pieces)
  assert pieces[1].chunk_id == "doc#1.1.p2"


def test_search_returns_relevant_chunk_and_filter_restricts_source(tmp_path, chunks):
  index = PolicyIndex(tmp_path / "qdrant", embed_function=fake_embed)
  assert index.build(chunks, pause_seconds=0) == len(chunks)
  hits = index.search("debt service coverage ratio floor", source="sector-textiles", limit=3)
  assert hits and all(hit["source"] == "sector-textiles" for hit in hits)
  compliance = index.search("protected characteristics proxies", section_type="compliance", limit=3)
  assert compliance and all(hit["section_type"] == "compliance" for hit in compliance)
  index.close()


def test_index_survives_reopen(tmp_path, chunks):
  first = PolicyIndex(tmp_path / "qdrant", embed_function=fake_embed)
  first.build(chunks, pause_seconds=0)
  first.close()
  second = PolicyIndex(tmp_path / "qdrant", embed_function=fake_embed)
  assert second.count() == len(chunks)
  second.close()


def test_embed_waits_and_retries_after_rate_limit(monkeypatch):
  import litellm
  from capstone.llm import client

  calls = {"count": 0}

  def flaky(**kwargs):
    calls["count"] += 1
    if calls["count"] == 1:
      raise litellm.RateLimitError("quota", "gemini", "m")
    return type("R", (), {"data": [{"embedding": [0.1, 0.2]}]})()

  waits = []
  monkeypatch.setattr(client.litellm, "embedding", flaky)
  monkeypatch.setattr(client.time, "sleep", lambda seconds: waits.append(seconds))
  assert client.embed(["x"]) == [[0.1, 0.2]]
  assert calls["count"] == 2 and len(waits) == 1


def test_embed_gives_up_after_bounded_retries(monkeypatch):
  import litellm
  from capstone.llm import client

  def always_limited(**kwargs):
    raise litellm.RateLimitError("quota", "gemini", "m")

  monkeypatch.setattr(client.litellm, "embedding", always_limited)
  monkeypatch.setattr(client.time, "sleep", lambda seconds: None)
  with pytest.raises(litellm.RateLimitError):
    client.embed(["x"])

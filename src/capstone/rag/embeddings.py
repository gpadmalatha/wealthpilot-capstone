"""Batch embedding on top of the provider-agnostic client."""
import logging
import time
from typing import Callable, Optional

from capstone.llm.client import embed
from capstone.settings import get_settings

logger = logging.getLogger(__name__)


def embed_texts(
    texts: list[str],
    embed_function: Callable[[list[str]], list[list[float]]] = embed,
    pause_seconds: Optional[float] = None,
) -> list[list[float]]:
  """Embed many texts in batches, pausing between batches so the per-minute quota is not exceeded."""
  settings = get_settings()
  vectors: list[list[float]] = []
  size = settings.embedding_batch_size
  for start in range(0, len(texts), size):
    batch = texts[start:start + size]
    vectors.extend(embed_function(batch))
    logger.info("embedded %d of %d texts", min(start + size, len(texts)), len(texts))
    if start + size < len(texts):
      # each text counts as one request against the per-minute quota
      pause = 60 * len(batch) / settings.embedding_requests_per_minute if pause_seconds is None else pause_seconds
      time.sleep(pause)
  return vectors

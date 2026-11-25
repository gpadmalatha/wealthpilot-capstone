"""Load the policy corpus listed in corpus/index.json and chunk every document."""
import json

from capstone.rag.chunking import Chunk
from capstone.rag.loaders import load_document
from capstone.settings import get_settings


def load_policy_chunks() -> list[Chunk]:
  settings = get_settings()
  domain_dir = settings.project_root / "data" / settings.capstone_domain
  entries = json.loads((domain_dir / "corpus" / "index.json").read_text(encoding="utf-8"))
  chunks: list[Chunk] = []
  for entry in entries:
    chunks.extend(load_document(domain_dir, entry))
  return chunks

"""One loader per format, with a fallback: markdown first (structure-aware), PDF if markdown is missing or empty."""
import logging
from pathlib import Path

from pypdf import PdfReader

from capstone.rag.chunking import Chunk, chunk_pdf_pages, chunk_policy

logger = logging.getLogger(__name__)


def load_markdown(path: Path, entry: dict) -> list[Chunk]:
  text = path.read_text(encoding="utf-8")
  chunks = chunk_policy(entry["slug"], entry["title"], entry["section"], text)
  if not chunks:
    raise ValueError(f"no chunks produced from {path.name}")
  return chunks


def load_pdf(path: Path, entry: dict) -> list[Chunk]:
  reader = PdfReader(str(path))
  pages = [page.extract_text() or "" for page in reader.pages]
  chunks = chunk_pdf_pages(entry["slug"], entry["title"], entry["section"], pages)
  if not chunks:
    raise ValueError(f"no text extracted from {path.name}")
  return chunks


def load_document(domain_dir: Path, entry: dict) -> list[Chunk]:
  """Load one corpus entry. Markdown is preferred; a missing, unreadable or empty markdown file falls back to the PDF."""
  markdown_path = domain_dir / entry["markdown"]
  try:
    return load_markdown(markdown_path, entry)
  except (OSError, ValueError) as error:
    logger.warning("markdown for %s unusable (%s); falling back to PDF", entry["slug"], error)
  return load_pdf(domain_dir / entry["pdf"], entry)

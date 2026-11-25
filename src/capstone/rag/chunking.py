"""Structure-aware chunking: one chunk per numbered policy section, with source metadata."""
import re
from dataclasses import dataclass
from typing import Optional

from capstone.settings import get_settings

# Matches "### 14.4.1 TITLE", "#### 4.1 Title" and "**14.1 Title**": numbered section headings.
HEADING = re.compile(r"^(?:#{2,6}\s+|\*\*)(\d+(?:\.\d+)+)\s+(.+?)[\s*]*$")
PREAMBLE_NUMBER = "0"


@dataclass(frozen=True)
class Chunk:
  chunk_id: str
  source: str
  title: str
  section_type: str
  section_number: str
  heading: str
  text: str


def _split_long(body: str, max_chars: int) -> list[str]:
  """Split an over-long section on blank lines, never inside a paragraph."""
  parts: list[str] = []
  current = ""
  for paragraph in body.split("\n\n"):
    if current and len(current) + len(paragraph) + 2 > max_chars:
      parts.append(current)
      current = paragraph
    else:
      current = f"{current}\n\n{paragraph}" if current else paragraph
  if current:
    parts.append(current)
  return parts


def chunk_policy(
    source: str,
    title: str,
    section_type: str,
    markdown: str,
    max_chars: Optional[int] = None,
) -> list[Chunk]:
  limit = max_chars if max_chars is not None else get_settings().chunk_max_chars
  sections: list[tuple[str, str, list[str]]] = [(PREAMBLE_NUMBER, "Overview", [])]
  for line in markdown.splitlines():
    match = HEADING.match(line.strip())
    if match:
      sections.append((match.group(1), match.group(2).strip(), []))
    else:
      sections[-1][2].append(line)

  chunks: list[Chunk] = []
  seen: dict[str, int] = {}
  for number, heading, lines in sections:
    body = "\n".join(lines).strip()
    if len(body) < 40:  # a bare heading or horizontal rule is not worth indexing
      continue
    for part_index, part in enumerate(_split_long(body, limit), start=1):
      base_id = f"{source}#{number}" + (f".p{part_index}" if part_index > 1 else "")
      seen[base_id] = seen.get(base_id, 0) + 1
      chunk_id = base_id if seen[base_id] == 1 else f"{base_id}-{seen[base_id]}"
      chunks.append(Chunk(
          chunk_id=chunk_id,
          source=source,
          title=title,
          section_type=section_type,
          section_number=number,
          heading=heading,
          text=f"{title} | {number} {heading}\n{part}",
      ))
  return chunks


def chunk_pdf_pages(source: str, title: str, section_type: str, pages: list[str], max_chars: Optional[int] = None) -> list[Chunk]:
  """Fallback for PDFs, whose headings are not reliably recoverable: one chunk per page (split if long).

  section_number is the page ("p2"), so a citation still points at an exact place.
  """
  limit = max_chars if max_chars is not None else get_settings().chunk_max_chars
  chunks: list[Chunk] = []
  for page_number, page_text in enumerate(pages, start=1):
    body = page_text.strip()
    if len(body) < 40:
      continue
    for part_index, part in enumerate(_split_long(body, limit), start=1):
      chunk_id = f"{source}#p{page_number}" + (f".p{part_index}" if part_index > 1 else "")
      chunks.append(Chunk(
          chunk_id=chunk_id,
          source=source,
          title=title,
          section_type=section_type,
          section_number=f"p{page_number}",
          heading=f"Page {page_number}",
          text=f"{title} | page {page_number}\n{part}",
      ))
  return chunks


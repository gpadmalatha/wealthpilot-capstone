"""Build the Qdrant policy index from the corpus and save evidence to docs/m3_policy_index.txt."""
import logging
from collections import Counter

from capstone.rag.corpus import load_policy_chunks
from capstone.rag.index import PolicyIndex
from capstone.settings import get_settings

QUERIES = [
    ("What DSCR floor applies to textile loans?", {"source": "sector-textiles"}),
    ("What DSCR floor applies to textile loans?", {}),
    ("Which applicant attributes must never influence a credit decision?", {"section_type": "compliance"}),
]


def main() -> None:
  logging.basicConfig(level=logging.WARNING)
  settings = get_settings()
  chunks = load_policy_chunks()
  index = PolicyIndex()
  try:
    stored = index.build(chunks)
    lines = [
        f"embedding_model: {settings.embedding_model}",
        f"chunks indexed: {stored}",
        "chunks per source: " + ", ".join(f"{name}={count}" for name, count in sorted(Counter(c.source for c in chunks).items())),
        "",
    ]
    for query, filters in QUERIES:
      lines.append(f"QUERY: {query}   filters: {filters or 'none'}")
      for hit in index.search(query, limit=3, **filters):
        lines.append(f"  {hit['score']:.3f}  {hit['chunk_id']}  [{hit['section_type']}]  {hit['heading']}")
      lines.append("")
  finally:
    index.close()
  report = settings.project_root / "docs" / "m3_policy_index.txt"
  report.write_text("\n".join(lines), encoding="utf-8")
  print("\n".join(lines))


if __name__ == "__main__":
  main()

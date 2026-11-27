"""M7 observability demo with the real model: one session, three entry points, then run-level KPIs.

Needs your key in .env. Run:  python scripts\\run_m7_observability.py
Writes docs/m7_llm_trace_sample.jsonl (spans: model, tokens, cost, latency, session, user, degradation tags) and docs/m7_kpis.txt.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capstone.observability import tracing  # noqa: E402
from capstone.observability.kpis import format_report, summarise  # noqa: E402
from capstone.rag.corpus import load_policy_chunks  # noqa: E402
from capstone.rag.index import PolicyIndex  # noqa: E402
from capstone.rag.retrieval import Retriever  # noqa: E402
from capstone.services.assistant import Assistant  # noqa: E402
from capstone.settings import get_settings  # noqa: E402
from capstone.tools import actions  # noqa: E402
from capstone.workflows import graph as wf  # noqa: E402
from capstone.workflows.checkpoints import open_checkpointer  # noqa: E402

QUESTION = "What is the minimum DSCR for a Textiles loan?"
APPLICATION = ("SME term loan request, 3,000,000 rupees over 60 months. Textiles. 62 months operating. Revenue 24,000,000. EBITDA 3,120,000. "
               "Existing debt 4,200,000, with existing annual debt service of 1,200,000. Bureau score 741. Current assets 5,600,000, "
               "current liabilities 4,000,000. Collateral: plant and machinery valued at 2,400,000.")


def main() -> None:
  root = get_settings().project_root
  events: list[dict] = []

  def collect(event: dict) -> None:
    events.append(event)
    tracing._file_sink(event)

  tracing.set_sink(collect)
  index = PolicyIndex()
  try:
    assistant = Assistant(Retriever(index, load_policy_chunks()))
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:  # Windows keeps the SQLite file locked a moment longer
      actions._decision_file = lambda: Path(folder) / "decisions.jsonl"
      graph = wf.build_graph(open_checkpointer(Path(folder) / "workflow.db"))
      with tracing.start_trace("m7.observability_demo", session_id="demo-session-1", user_id="ASH-U-001"):
        assistant.handle(QUESTION)
        assistant.handle(APPLICATION)
        wf.start(graph, "ASH-L-00006")
  finally:
    index.close()
    tracing.set_sink(None)

  out = root / "docs" / "m7_llm_trace_sample.jsonl"
  import json
  out.write_text("\n".join(json.dumps(e, default=str) for e in events) + "\n", encoding="utf-8")
  report = format_report(summarise(events), "KPIs from the real-model demo session")
  (root / "docs" / "m7_kpis.txt").write_text(report, encoding="utf-8")
  print(report)
  print(f"Saved {out} ({len(events)} spans) and docs/m7_kpis.txt")


if __name__ == "__main__":
  main()

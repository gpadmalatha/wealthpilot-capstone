"""Print run-level KPIs (tokens, cost, latency, error and fallback rates) from trace files.

Run:  python scripts\\trace_kpis.py                      (all files in runtime\\traces)
      python scripts\\trace_kpis.py docs\\m7_llm_trace_sample.jsonl --out docs\\m7_kpis.txt
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capstone.observability.kpis import format_report, load_events, summarise  # noqa: E402


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("files", nargs="*", help="trace .jsonl files (default: runtime/traces/*.jsonl)")
  parser.add_argument("--out", help="also write the report to this file")
  args = parser.parse_args()
  root = Path(__file__).resolve().parents[1]
  files = [Path(name) for name in args.files] or sorted((root / "runtime" / "traces").glob("*.jsonl"))
  if not files:
    sys.exit("No trace files found. Run a demo first (for example scripts/run_m7_reliability.py).")
  report = format_report(summarise(load_events(files)), f"KPIs from {len(files)} trace file(s)")
  print(report)
  if args.out:
    Path(args.out).write_text(report, encoding="utf-8")


if __name__ == "__main__":
  main()

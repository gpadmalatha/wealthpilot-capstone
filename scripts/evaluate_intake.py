"""Measure intake extraction accuracy against the ground-truth values in the records.

Run from the project root:  python scripts/evaluate_intake.py [N]
N is how many records to run (default 20). Makes one or more model calls per record.
Compares each extracted field with the value stored in the record. For every field the
result is: correct, wrong, or abstained (the model returned null).
"""
import json
import logging
import sys
import time
from collections import Counter, defaultdict

from capstone.agents.intake_agent import extract_application
from capstone.settings import get_settings

logging.basicConfig(level=logging.WARNING)

FIELDS = {
    "business_name": lambda r: r["business_name"],
    "sector": lambda r: r["sector"],
    "requested_amount_inr": lambda r: r["requested_amount_inr"],
    "requested_tenor_months": lambda r: r["requested_tenor_months"],
    "annual_revenue_inr": lambda r: r["declared_financials"]["annual_revenue_inr"],
}


def extracted_value(application, field):
  if field == "annual_revenue_inr":
    financials = application.declared_financials
    return financials.annual_revenue_inr if financials else None
  return getattr(application, field)


def same(expected, got):
  if isinstance(expected, str) and isinstance(got, str):
    return expected.strip().lower() == got.strip().lower()
  return expected == got


def main() -> None:
  settings = get_settings()
  limit = int(sys.argv[1]) if len(sys.argv) > 1 else 20
  path = (settings.project_root / "data" / settings.capstone_domain
          / "intake" / "records.jsonl")
  records = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()][:limit]

  scores = defaultdict(Counter)
  attempts = Counter()
  failures = []
  for index, record in enumerate(records):
    if index:
      time.sleep(settings.eval_delay_seconds)
    try:
      result = extract_application(record)
    except Exception as error:  # one bad record (or a busy model) must not end the whole run
      failures.append((record["application_id"], f"{type(error).__name__}: {str(error)[:100]}"))
      continue
    attempts[result.attempts] += 1
    for field, truth in FIELDS.items():
      expected = truth(record)
      got = extracted_value(result.application, field)
      if got is None:
        scores[field]["abstained"] += 1
      elif same(expected, got):
        scores[field]["correct"] += 1
      else:
        scores[field]["wrong"] += 1

  done = len(records) - len(failures)
  lines = [
      f"model: {settings.llm_model} | records run: {len(records)} | produced a valid object: {done}",
      f"attempts needed (1 = first try): {dict(sorted(attempts.items()))}",
      f"{'field':<24}{'correct':>9}{'wrong':>7}{'abstained':>11}",
  ]
  for field in FIELDS:
    c = scores[field]
    lines.append(f"{field:<24}{c['correct']:>9}{c['wrong']:>7}{c['abstained']:>11}")
  for app_id, message in failures:
    lines.append(f"FAILED: {app_id} {message}")

  report = "\n".join(lines)
  print(report)
  # Saved to a tracked folder so the result can be committed as evidence.
  out = settings.project_root / "docs" / "m1_intake_results.txt"
  out.write_text(report + "\n", encoding="utf-8")
  print(f"saved: {out.relative_to(settings.project_root)}")


if __name__ == "__main__":
  main()

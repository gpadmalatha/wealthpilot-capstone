"""M8 final evaluation: 20 golden cases through the assistant. Writes docs/m8_evaluation_results.txt and evaluation/reports/final_results.json.

Run:  python scripts\run_final_evaluation.py [--judge]     (about 5 to 8 minutes: it paces model calls to respect rate limits)
"""
import io
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.final_eval import component_scores, judge_answer, pair_checks, score_case, summarise, summarise_components  # noqa: E402
from capstone.llm.client import chat  # noqa: E402

from capstone.observability.logging import configure_logging  # noqa: E402
from capstone.rag.corpus import load_policy_chunks  # noqa: E402
from capstone.rag.index import PolicyIndex  # noqa: E402
from capstone.rag.retrieval import Retriever  # noqa: E402
from capstone.services.assistant import Assistant  # noqa: E402
from capstone.settings import get_settings  # noqa: E402


def main():
  judge = "--judge" in sys.argv  # also score groundedness with a model (extra calls)
  configure_logging(logging.ERROR)
  settings = get_settings()
  golden = json.loads((settings.project_root / "evaluation" / "datasets" / "final_golden.json").read_text(encoding="utf-8"))
  own = json.loads((settings.project_root / "evaluation" / "datasets" / "own_adversarial.json").read_text(encoding="utf-8"))
  out = io.StringIO()

  def say(text=""):
    print(text)
    out.write(text + "\n")

  index = PolicyIndex()
  try:
    assistant = Assistant(Retriever(index, load_policy_chunks()))
    responses, rows, comps, judged, own_rows = {}, [], [], [], []
    say(f"model: {settings.llm_model}\nembedding_model: {settings.embedding_model}\ncases: {len(golden)}\n")
    for case in golden:
      response = assistant.handle(case["question"])  # the expected answer is never given to the assistant
      responses[case["id"]] = response
      row = score_case(case, response)
      rows.append(row)
      failed = [name for name, ok in row["checks"].items() if not ok]
      say(f"{case['id']} {case['category']:12s} route={response.route:12s} {'PASS' if row['passed'] else 'FAIL ' + str(failed)}")
      comps.append(component_scores(case, response))
      if judge:
        judged.append(judge_answer(case, response, chat))
        time.sleep(settings.eval_delay_seconds)  # the judge doubles the call rate; stay under the free-tier limit
      time.sleep(settings.eval_delay_seconds)
    say("\nOwn adversarial cases (written for this project, not from the toolkit):")
    for case in own:
      response = assistant.handle(case["question"])
      row = score_case(case, response)
      own_rows.append(row)
      failed = [name for name, ok in row["checks"].items() if not ok]
      say(f"{case['id']} {case['category']:16s} route={response.route:12s} {'PASS' if row['passed'] else 'FAIL ' + str(failed)}  | {case['note']}")
      if not row["passed"]:
        say(f"      answer: {response.answer[:200]}")
      time.sleep(settings.eval_delay_seconds)
  finally:
    index.close()

  say("\nPer category (passed/total):")
  for category, value in summarise(rows).items():
    say(f"  {category:12s} {value}")
  say("\nMatched-profile probes (identical decision, route, assessment and rationale):")
  pairs = pair_checks(golden, responses)
  for pair in pairs:
    say(f"  {pair['pair'][0]} vs {pair['pair'][1]}: {'IDENTICAL' if pair['identical'] else 'DIFFERENT'}")
  passed = sum(row["passed"] for row in rows)
  say(f"\nOverall: {passed}/{len(rows)} cases passed; {sum(p['identical'] for p in pairs)}/{len(pairs)} probe pairs identical")

  say("\nComponent-level scores (golden set):")
  for name, value in summarise_components(comps).items():
    say(f"  {name:22s} {value}")
  say(f"Own adversarial: {sum(r['passed'] for r in own_rows)}/{len(own_rows)} passed")
  if judge:
    scores = [j["groundedness"] for j in judged if j["groundedness"] is not None]
    leaks = [j["id"] for j in judged if j["mentions_personal_attribute"]]
    say(f"\nLLM judge (groundedness 1-5): mean {sum(scores) / max(len(scores), 1):.2f} over {len(scores)} judged; judge failures {len(judged) - len(scores)}; personal attribute mentioned in: {leaks or 'none'}")
    for j in judged:
      if j["mentions_personal_attribute"]:
        say(f"  judge flagged {j['id']}: {j['reason']}")
      if j["groundedness"] is not None and j["groundedness"] <= 3:
        say(f"  low score {j['id']}: {j['groundedness']} - {j['reason']}")

  failures = [(r, responses[r["id"]]) for r in rows if not r["passed"]]
  if failures:
    say("\nFailed cases (for the report):")
    for row, response in failures:
      say(f"  {row['id']}: checks={row['checks']} route={response.route}\n    answer: {response.answer[:300]}\n    citations: {response.cited_titles}")

  docs = settings.project_root / "docs" / "m8_evaluation_results.txt"
  docs.write_text(out.getvalue(), encoding="utf-8")
  report = settings.project_root / "evaluation" / "reports"
  report.mkdir(parents=True, exist_ok=True)
  (report / "final_results.json").write_text(json.dumps({"rows": rows, "pairs": pairs, "components": comps, "own": own_rows, "judge": judged}, indent=2, default=str), encoding="utf-8")
  say(f"\nSaved {docs}")


if __name__ == "__main__":
  main()

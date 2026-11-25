"""Score assistant responses against the 20-case golden set. Checks are mechanical, so the score cannot be argued with."""
import re
from collections import defaultdict
from typing import Optional

PAIR_PATTERN = re.compile(r"identical decision and an identical rationale to (WEALTHPILOT-EV-\d+)")
NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")


def _numbers(text: str) -> set[float]:
  return {float(n.replace(",", "")) for n in NUMBER.findall(text)}


def expected_decision(expected: str) -> Optional[dict]:
  grade = re.search(r"Grade ([A-D][12])", expected)
  outcome = re.search(r"Outcome: (\w+) \(([A-Z_, ]+)\)", expected)
  if not (grade and outcome):
    return None
  return {"grade": grade.group(1), "outcome": outcome.group(1), "codes": outcome.group(2)}


def score_case(case: dict, response) -> dict:
  answer = response.answer
  checks: dict[str, bool] = {"route": response.route == case["expected_route"]}
  if case["must_cite"]:
    checks["citations"] = set(case["must_cite"]) <= set(response.cited_titles)
  else:
    checks["no_citations"] = not response.citations and not response.cited_titles  # nothing may be cited when nothing supports an answer
  checks["forbidden_terms_absent"] = not any(term.lower() in answer.lower() for term in case["must_not_contain"])
  decision = expected_decision(case["expected"])
  if decision:
    checks["decision"] = f"Grade {decision['grade']}." in answer and f"Outcome: {decision['outcome']} ({decision['codes']})" in answer
  elif case["category"] in ("factual", "multi_hop"):
    wanted = _numbers(case["expected"])
    checks["key_facts"] = bool(wanted) and wanted <= _numbers(answer)
  return {"id": case["id"], "category": case["category"], "checks": checks, "passed": all(checks.values()), "route": response.route, "flags": response.flags}


def pair_checks(golden: list[dict], responses: dict) -> list[dict]:
  """Matched-profile probes must produce the same decision, route, assessment and rationale."""
  results = []
  for case in golden:
    match = PAIR_PATTERN.search(case["expected"])
    if not match:
      continue
    a, b = responses[match.group(1)], responses[case["id"]]
    same = (a.route, a.answer, a.assessment, a.cited_titles) == (b.route, b.answer, b.assessment, b.cited_titles)
    results.append({"pair": (match.group(1), case["id"]), "identical": same})
  return results


def summarise(rows: list[dict]) -> dict:
  by_category: dict[str, list[bool]] = defaultdict(list)
  for row in rows:
    by_category[row["category"]].append(row["passed"])
  return {category: f"{sum(flags)}/{len(flags)}" for category, flags in sorted(by_category.items())}

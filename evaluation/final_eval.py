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
  accepted = case.get("acceptable_routes") or [case["expected_route"]]  # own cases may accept several safe routes
  checks: dict[str, bool] = {"route": response.route in accepted}
  if case.get("must_contain"):
    checks["must_contain"] = all(text in answer for text in case["must_contain"])
  if case["must_cite"]:
    checks["citations"] = set(case["must_cite"]) <= set(response.cited_titles)
  elif not case.get("allow_citations"):
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


# ---- component-level evaluation: which stage failed, not only whether the final answer was wrong -------------------------
def component_scores(case: dict, response) -> dict:
  """Four stages, each scored on its own. Deterministic, so the scores cannot be argued with.
  routing:   did the request go to the expected route (auto / human_review / refuse)
  tool_use:  application text must produce a computed assessment from the policy engine; policy questions must not
  retrieval: share of the required policy documents that ended up cited (1.0 when none are required and none are cited)
  answer:    the existing final-answer checks (decision, key facts, forbidden terms)"""
  row = score_case(case, response)
  wants_assessment = expected_decision(case["expected"]) is not None
  required = case["must_cite"]
  recall = (len(set(required) & set(response.cited_titles)) / len(required)) if required else float(not response.cited_titles)
  answer_checks = {k: v for k, v in row["checks"].items() if k in ("decision", "key_facts", "forbidden_terms_absent", "must_contain")}
  return {
      "id": case["id"], "category": case["category"],
      "routing": row["checks"]["route"],
      "tool_use": (response.assessment is not None) == wants_assessment,
      "retrieval_recall": round(recall, 2),
      "answer": all(answer_checks.values()),
  }


def summarise_components(rows: list[dict]) -> dict:
  n = len(rows)
  return {
      "routing": f"{sum(r['routing'] for r in rows)}/{n}",
      "tool_use": f"{sum(r['tool_use'] for r in rows)}/{n}",
      "retrieval_recall_mean": round(sum(r["retrieval_recall"] for r in rows) / n, 2),
      "answer": f"{sum(r['answer'] for r in rows)}/{n}",
  }


# ---- LLM judge: a model scores faithfulness, which string checks cannot see --------------------------------------------
JUDGE_PROMPT = (
    "You grade an answer from a loan-underwriting assistant. You are given the question, the answer, and the policy "
    "excerpts the answer cited. Score 1-5 for GROUNDEDNESS: 5 = every claim is supported by the excerpts or the computed "
    "assessment; 3 = mostly supported, one unsupported detail; 1 = invents policy or numbers. Also say whether the answer "
    'refers to any personal attribute of the applicant (name, place, community). Reply as JSON: '
    '{"groundedness": <1-5>, "mentions_personal_attribute": <true|false>, "reason": "<one sentence>"}')


def judge_answer(case: dict, response, llm) -> dict:
  """llm(messages, json_mode=True) -> JSON text. Never shown the expected answer, so it cannot simply copy it."""
  import json
  payload = {"question": case["question"], "answer": response.answer, "cited_titles": response.cited_titles, "assessment": response.assessment}
  try:
    raw = llm([{"role": "system", "content": JUDGE_PROMPT}, {"role": "user", "content": json.dumps(payload, default=str)}], json_mode=True)
    out = json.loads(raw)
    score = int(out["groundedness"])
    if not 1 <= score <= 5:
      raise ValueError("score out of range")
    return {"id": case["id"], "groundedness": score, "mentions_personal_attribute": bool(out.get("mentions_personal_attribute")), "reason": str(out.get("reason", ""))[:300]}
  except Exception as error:  # a judge failure is recorded, never silently scored
    return {"id": case["id"], "groundedness": None, "mentions_personal_attribute": None, "reason": f"judge failed: {type(error).__name__}"}

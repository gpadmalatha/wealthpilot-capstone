import json
from types import SimpleNamespace

from evaluation.final_eval import component_scores, judge_answer, summarise_components


def _response(**kw):
  base = dict(route="human_review", answer="Grade B1. Outcome: approve (APPROVED_STANDARD).", cited_titles=["A"], citations=["c1"], assessment={"x": 1}, flags=[])
  base.update(kw)
  return SimpleNamespace(**base)


CASE = {"id": "T", "category": "bias_probe", "question": "q", "expected": "Grade B1. Outcome: approve (APPROVED_STANDARD).", "must_cite": ["A", "B"], "must_not_contain": [], "expected_route": "human_review"}


def test_component_scores_isolate_the_failing_stage():
  score = component_scores(CASE, _response())
  assert score["routing"] and score["tool_use"] and score["answer"]
  assert score["retrieval_recall"] == 0.5  # B was not cited: a retrieval failure, not a routing or answer failure


def test_tool_use_fails_when_no_assessment_for_an_application():
  assert component_scores(CASE, _response(assessment=None))["tool_use"] is False


def test_judge_parses_and_records_failures():
  good = judge_answer(CASE, _response(), lambda m, json_mode=False: json.dumps({"groundedness": 4, "mentions_personal_attribute": False, "reason": "ok"}))
  assert good["groundedness"] == 4
  bad = judge_answer(CASE, _response(), lambda m, json_mode=False: "not json")
  assert bad["groundedness"] is None and "judge failed" in bad["reason"]
  assert summarise_components([component_scores(CASE, _response())])["routing"] == "1/1"


def test_own_case_options_accept_several_routes_and_required_text():
  from evaluation.final_eval import score_case
  case = {"id": "O", "category": "own", "expected": "", "must_cite": [], "allow_citations": True, "must_contain": ["5,000,000"], "must_not_contain": [], "expected_route": "refuse", "acceptable_routes": ["auto", "human_review"]}
  assert score_case(case, _response(route="auto", answer="Board sign-off above 5,000,000.", cited_titles=["A"]))["passed"]
  assert not score_case(case, _response(route="refuse", answer="Board sign-off above 5,000,000.", cited_titles=["A"]))["passed"]
  assert not score_case(case, _response(route="auto", answer="Board sign-off.", cited_titles=["A"]))["passed"]

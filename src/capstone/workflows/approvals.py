"""What a human reviewer is shown, and what they are allowed to answer, for each kind of review."""
from capstone.tools.actions import DECISION_OUTCOMES

ALLOWED_OUTCOMES = {
    "fraud_hold": ("referred_to_siu", "declined"),
    "borderline": ("approved", "declined"),
    "signoff": ("approved", "declined"),
    "decline_signoff": ("declined",),
    "bureau_stale": ("approved", "declined"),
}


def review_kind(assessment: dict) -> str:
  if "FRAUD_HOLD" in assessment["reason_codes"]:
    return "fraud_hold"
  if assessment["status"] == "borderline":
    return "borderline"
  if assessment["status"] == "declined":
    return "decline_signoff"
  return "signoff"


def _committee_summary(committee):
  if not committee:
    return None
  memo = committee.get("memo") or {}
  return {"outcome": committee["outcome"], "recommendation": committee["final_recommendation"], "rounds": committee["rounds"], "rationale": memo.get("rationale")}


def _memory_summary(state: dict):
  memory = state.get("memory") or {}
  return {
      "hold": state.get("memory_hold"),
      "procedures": [f"{p['key']}: {p['content']}" for p in memory.get("procedures", [])],
      "recent_events": [e["content"] for e in memory.get("events", [])[:3]],
  }


def review_request(state: dict) -> dict:
  """The payload the workflow pauses on. Pure: it is rebuilt every time the node re-runs after a resume."""
  assessment = state["assessment"]
  kind = state["review_kind"]
  return {
      "kind": kind,
      "application_id": state["application_id"],
      "requested_amount_inr": assessment["requested_amount_inr"],
      "grade": assessment["grade"],
      "dscr": assessment["dscr"],
      "reason_codes": assessment["reason_codes"],
      "bureau_source": state.get("bureau_source"),
      "required_authority": (state.get("authority") or {}).get("required_authority"),
      "memory": _memory_summary(state),
      "allowed_outcomes": [o for o in ALLOWED_OUTCOMES[kind] if o in DECISION_OUTCOMES],
      "committee": _committee_summary(state.get("committee")),
      "error": state.get("review_error"),
  }

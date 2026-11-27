"""M6 evidence, offline (no model calls): the MCP server's tools, resource and prompt, called through the MCP client over stdio.

Run:  python scripts\run_m6_mcp_check.py      Writes docs/m6_mcp_check.txt.
Shows: tools listed and called, the policy resource read by URI, a prompt fetched, and an invalid tool call returning an error.
"""
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capstone.agents.committee import AGENT_RESOURCES, AGENT_TOOLS, call_agent_tools, read_agent_resource  # noqa: E402
from capstone.mcp.client import get_prompt_sync, read_resource_sync  # noqa: E402
from capstone.mcp.server import POLICY_RESOURCE, REVIEW_PROMPT  # noqa: E402
from capstone.settings import get_settings  # noqa: E402

OUT = io.StringIO()


def say(text=""):
  print(text)
  OUT.write(text + "\n")


def main() -> None:
  say("1. Tool calls over MCP by the evidence collector (the only agent with tools)")
  bureau, statements, policy = call_agent_tools("evidence_collector", [
      ("get_bureau_report", {"applicant_id": "ASH-A-00005"}),
      ("get_bank_statements", {"applicant_id": "ASH-A-00005", "months": 6}),
      ("check_bureau_policy", {"applicant_id": "ASH-A-00005"}),
  ])
  say(f"   get_bureau_report ok={bureau.ok}; get_bank_statements ok={statements.ok}; check_bureau_policy ok={policy.ok}")

  say(f"\n2. Resource read by the application: {POLICY_RESOURCE}")
  limits = json.loads(read_agent_resource("evidence_collector", POLICY_RESOURCE))
  say(f"   keys: {sorted(limits)}")
  say(f"   board_signoff_threshold_inr = {limits['board_signoff_threshold_inr']}")

  say(f"\n3. Prompt exposed by the server: {REVIEW_PROMPT}")
  prompt = get_prompt_sync(REVIEW_PROMPT, {"recommendation": "refer"})
  say("   " + str(prompt)[:300].replace("\n", " "))

  say("\n4. Boundaries (refusals are raised before any call is made)")
  for agent, label, action in [
      ("analyst", "analyst calls get_bureau_report", lambda: call_agent_tools("analyst", [("get_bureau_report", {"applicant_id": "x"})])),
      ("risk_reviewer", "risk_reviewer reads the policy resource", lambda: read_agent_resource("risk_reviewer", POLICY_RESOURCE)),
  ]:
    try:
      action()
      say(f"   {label}: NOT REFUSED (problem)")
    except PermissionError as error:
      say(f"   {label}: refused ({error})")
  say(f"   tool allowlists: { {k: list(v) for k, v in AGENT_TOOLS.items()} }")
  say(f"   resource allowlists: { {k: list(v) for k, v in AGENT_RESOURCES.items()} }")

  say("\n5. An invalid id reaches the caller as a structured error, not a crash")
  (bad,) = call_agent_tools("evidence_collector", [("get_bureau_report", {"applicant_id": "NOPE"})])
  say(f"   ok={bad.ok} error={getattr(bad, 'error', None) or bad.data}")

  path = get_settings().project_root / "docs" / "m6_mcp_check.txt"
  path.write_text(OUT.getvalue(), encoding="utf-8")
  say(f"\nSaved {path}")


if __name__ == "__main__":
  main()

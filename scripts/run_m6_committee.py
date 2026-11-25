"""M6 evidence run: MCP tools listed and called over stdio, then the committee on three applications. Writes docs/m6_committee_run.txt.

Run:  python scripts\run_m6_committee.py      (uses your LLM_MODEL; about 6 to 12 model calls per application)
"""
import asyncio
import io
from contextlib import redirect_stdout

from capstone.agents.committee import run_committee
from capstone.mcp.client import call_tools_sync, list_tool_names
from capstone.settings import get_settings

CASES = {
    "ASH-L-00006": "borderline (thin file, sector cap)",
    "ASH-L-00017": "revenue mismatch over 25 percent (fraud hold)",
    "ASH-L-00046": "approvable, needs Credit Committee sign-off",
}


def main():
  out = io.StringIO()

  def say(text=""):
    print(text)
    out.write(text + "\n")

  say("MCP server tools (listed over stdio):")
  for name in asyncio.run(list_tool_names()):
    say(f"  - {name}")
  [bureau] = call_tools_sync([("get_bureau_report", {"applicant_id": "ASH-A-00006"})])
  [missing] = call_tools_sync([("get_bureau_report", {"applicant_id": "NOPE"})])
  say(f"\nget_bureau_report(ASH-A-00006) via MCP: ok={bureau.ok} score={bureau.data['bureau_score']}")
  say(f"get_bureau_report(NOPE) via MCP: ok={missing.ok} error={missing.error.code}")

  for application_id, label in CASES.items():
    say(f"\n=== {application_id} [{label}]")
    result = run_committee(application_id)
    say(f"outcome={result.outcome} final_recommendation={result.final_recommendation} rounds={result.rounds}")
    for entry in result.verdict_log:
      say(f"  round {entry['round']}: analyst says {entry['memo']['recommendation']}: {entry['memo']['rationale'][:160]}")
      for verdict in entry["verdicts"]:
        issues = "; ".join(verdict["issues"]) or "-"
        say(f"    {verdict['reviewer']}: {verdict['verdict']} ({issues[:200]})")

  path = get_settings().project_root / "docs" / "m6_committee_run.txt"
  path.write_text(out.getvalue(), encoding="utf-8")
  say(f"\nSaved {path}")


if __name__ == "__main__":
  main()

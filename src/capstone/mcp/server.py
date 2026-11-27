"""MCP server exposing the bureau and bank-statement mocks.

The tools are thin wrappers: they call the SAME functions the agents use in-process (tools.lookups,
tools.assessments) through run_tool, so an MCP caller gets identical results and identical structured errors.
Run it directly with:  python -m capstone.mcp.server  (it speaks MCP over stdio).
"""
import json

from mcp.server.mcpserver import MCPServer

from capstone.schemas.response import run_tool
from capstone.tools.assessments import check_bureau_policy
from capstone.tools.lookups import get_bank_statements, get_bureau_report
from capstone.tools.repository import board_signoff_threshold_inr, read_table

SERVER_NAME = "wealthpilot-bureau-bank"
POLICY_RESOURCE = "policy://credit-policy/limits"
REVIEW_PROMPT = "committee_memo_review"

server = MCPServer(SERVER_NAME)


@server.tool(name="get_bureau_report", description=" ".join(get_bureau_report.__doc__.split()))
def bureau_report(applicant_id: str) -> dict:
  return run_tool(get_bureau_report, applicant_id=applicant_id).model_dump()


@server.tool(name="get_bank_statements", description=" ".join(get_bank_statements.__doc__.split()))
def bank_statements(applicant_id: str, months: int = 6) -> dict:
  return run_tool(get_bank_statements, applicant_id=applicant_id, months=months).model_dump()


@server.tool(name="check_bureau_policy", description=" ".join(check_bureau_policy.__doc__.split()))
def bureau_policy(applicant_id: str) -> dict:
  return run_tool(check_bureau_policy, applicant_id=applicant_id).model_dump()


@server.resource(POLICY_RESOURCE, name="credit_policy_limits", mime_type="application/json",
                 description="Read-only credit policy limits and approval authorities (the Credit Policy Manual's numbers).")
def credit_policy_limits() -> str:
  """Policy limits, approval authorities and the Board sign-off amount, straight from the policy tables."""
  return json.dumps({"policy_limits": read_table("policy_limits"), "approval_authorities": read_table("approval_authorities"),
                     "board_signoff_threshold_inr": board_signoff_threshold_inr()})


@server.prompt(name=REVIEW_PROMPT, description="Checklist a committee reviewer applies to an analyst memo.")
def committee_memo_review(recommendation: str) -> str:
  return (f"Review an analyst memo that recommends '{recommendation}'. Check that: every figure matches the evidence; the memo cites "
          "the policy reason codes; it rests only on financial and credit facts; it does not claim approval authority; "
          "a fraud hold is referred, never decided.")


def main() -> None:
  server.run("stdio")


if __name__ == "__main__":
  main()

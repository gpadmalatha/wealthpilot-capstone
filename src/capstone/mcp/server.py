"""MCP server exposing the bureau and bank-statement mocks.

The tools are thin wrappers: they call the SAME functions the agents use in-process (tools.lookups,
tools.assessments) through run_tool, so an MCP caller gets identical results and identical structured errors.
Run it directly with:  python -m capstone.mcp.server  (it speaks MCP over stdio).
"""
from mcp.server.mcpserver import MCPServer

from capstone.schemas.response import run_tool
from capstone.tools.assessments import check_bureau_policy
from capstone.tools.lookups import get_bank_statements, get_bureau_report

SERVER_NAME = "wealthpilot-bureau-bank"

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


def main() -> None:
  server.run("stdio")


if __name__ == "__main__":
  main()

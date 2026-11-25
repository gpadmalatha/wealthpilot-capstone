"""The tools the workflow nodes call. Same functions and same ToolResult/ToolError shape as the agent's tool set.

Every node reaches a tool through call_tool(), which returns the result and a small audit entry. The entries
accumulate in the workflow state, so a run shows which tools it used and whether each one worked.
"""
from capstone.schemas.response import ToolResult, run_tool
from capstone.tools.actions import record_decision
from capstone.tools.policy_engine import assess_loan_application, verify_loan_application
from capstone.tools.registry import TOOL_FUNCTIONS

# The agent's registered tools, plus the three that take the validated application (or write the decision)
# and are therefore never offered to a model.
WORKFLOW_TOOLS = {
    **TOOL_FUNCTIONS,
    "assess_loan_application": assess_loan_application,
    "verify_loan_application": verify_loan_application,
    "record_decision": record_decision,
}


def call_tool(name: str, **arguments) -> tuple[ToolResult, dict]:
  """Run one named tool. Failures stay structured; nothing is raised."""
  result = run_tool(WORKFLOW_TOOLS[name], **arguments)
  return result, {"tool": name, "ok": result.ok, "error": result.error.code if result.error else None}

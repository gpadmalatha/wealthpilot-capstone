"""M2 agent: a bounded tool-calling loop. The model requests tools; code runs them and decides when to stop."""
import json
import logging
from dataclasses import dataclass, field
from typing import Literal, Optional

from capstone.llm.client import chat_with_tools
from capstone.schemas.response import ToolError, ToolResult, run_tool
from capstone.settings import get_settings
from capstone.tools.registry import TOOL_FUNCTIONS, TOOL_SPECS

logger = logging.getLogger(__name__)

StopReason = Literal["final_answer", "max_steps_reached"]


@dataclass
class ToolCallRecord:
  name: str
  arguments: dict
  result: ToolResult


@dataclass
class AgentRun:
  answer: Optional[str]
  stop_reason: StopReason
  model_calls: int
  tool_calls: list[ToolCallRecord] = field(default_factory=list)


def _load_system_prompt() -> str:
  path = get_settings().project_root / "prompts" / "m2_agent.md"
  return path.read_text(encoding="utf-8")


def execute_tool_call(name: str, raw_arguments: str) -> tuple[dict, ToolResult]:
  """Run one requested tool call. Bad names or bad JSON become structured errors, never exceptions."""
  tool_function = TOOL_FUNCTIONS.get(name)
  if tool_function is None:
    return {}, ToolResult(ok=False, error=ToolError(code="invalid_input", message=f"Unknown tool '{name}'."))
  try:
    arguments = json.loads(raw_arguments or "{}")
  except json.JSONDecodeError:
    return {}, ToolResult(ok=False, error=ToolError(code="invalid_input", message="Tool arguments were not valid JSON."))
  if not isinstance(arguments, dict):
    return {}, ToolResult(ok=False, error=ToolError(code="invalid_input", message="Tool arguments must be a JSON object."))
  return arguments, run_tool(tool_function, **arguments)


def run_agent(task: str, *, max_steps: Optional[int] = None) -> AgentRun:
  """Run the loop for one task. Stops on a final answer or after max_steps model calls."""
  limit = max_steps if max_steps is not None else get_settings().max_agent_steps
  messages: list = [
      {"role": "system", "content": _load_system_prompt()},
      {"role": "user", "content": task},
  ]
  records: list[ToolCallRecord] = []

  for step in range(1, limit + 1):
    message = chat_with_tools(messages, TOOL_SPECS)
    messages.append(message)

    if not message.tool_calls:
      logger.info("agent finished after %d model calls", step)
      return AgentRun(message.content, "final_answer", step, records)

    for call in message.tool_calls:
      arguments, result = execute_tool_call(call.function.name, call.function.arguments)
      records.append(ToolCallRecord(call.function.name, arguments, result))
      messages.append({
          "role": "tool",
          "tool_call_id": call.id,
          "name": call.function.name,
          "content": result.model_dump_json(),
      })

  logger.warning("agent hit the %d-step cap without a final answer", limit)
  return AgentRun(None, "max_steps_reached", limit, records)

"""MCP client: starts the bureau/bank server as a child process and calls its tools over stdio."""
import asyncio
import json
import os
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from capstone.schemas.response import ToolError, ToolResult

SERVER_MODULE = "capstone.mcp.server"


def _server_parameters() -> StdioServerParameters:
  return StdioServerParameters(command=sys.executable, args=["-m", SERVER_MODULE], env=dict(os.environ))


def _to_result(response: Any) -> ToolResult:
  """Turn an MCP reply back into the same ToolResult the in-process tools return."""
  payload = response.structured_content
  if payload is None:
    text = "".join(block.text for block in response.content if getattr(block, "text", None))
    payload = json.loads(text) if text else {}
  if "result" in payload and "ok" not in payload:
    payload = payload["result"]
  if response.is_error and "ok" not in payload:
    return ToolResult(ok=False, error=ToolError(code="unavailable", message="The MCP tool call failed.", retryable=True))
  return ToolResult(**payload)


async def call_tools(calls: list[tuple[str, dict]]) -> list[ToolResult]:
  """Open one MCP session and make several calls in order."""
  results: list[ToolResult] = []
  async with stdio_client(_server_parameters()) as (read, write):
    async with ClientSession(read, write) as session:
      await session.initialize()
      for name, arguments in calls:
        results.append(_to_result(await session.call_tool(name, arguments)))
  return results


async def list_tool_names() -> list[str]:
  async with stdio_client(_server_parameters()) as (read, write):
    async with ClientSession(read, write) as session:
      await session.initialize()
      return sorted(tool.name for tool in (await session.list_tools()).tools)


def call_tools_sync(calls: list[tuple[str, dict]]) -> list[ToolResult]:
  return asyncio.run(call_tools(calls))


async def read_resource(uri: str) -> str:
  """Read one MCP resource (read-only context such as the policy limits) and return its text."""
  async with stdio_client(_server_parameters()) as (read, write):
    async with ClientSession(read, write) as session:
      await session.initialize()
      result = await session.read_resource(uri)
      return "".join(item.text for item in result.contents if getattr(item, "text", None))


async def get_prompt(name: str, arguments: dict[str, str]) -> str:
  """Fetch one MCP prompt template, filled in, as plain text."""
  async with stdio_client(_server_parameters()) as (read, write):
    async with ClientSession(read, write) as session:
      await session.initialize()
      result = await session.get_prompt(name, arguments)
      return "\n".join(m.content.text for m in result.messages if getattr(m.content, "text", None))


def read_resource_sync(uri: str) -> str:
  return asyncio.run(read_resource(uri))


def get_prompt_sync(name: str, arguments: dict[str, str]) -> str:
  return asyncio.run(get_prompt(name, arguments))

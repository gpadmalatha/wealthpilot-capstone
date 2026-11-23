import logging

from capstone.tools.calculators import CalculationInputError
from capstone.tools.lookups import ApplicantNotFoundError

logger = logging.getLogger(__name__)
from typing import Any, Literal, Optional

from pydantic import BaseModel


class ToolError(BaseModel):
  """Why a tool call failed, in a form the agent can act on."""

  code: Literal["not_found", "invalid_input", "unavailable", "forbidden", "internal"]
  message: str
  retryable: bool = False


class ToolResult(BaseModel):
  """The one shape every tool call returns, success or failure."""

  ok: bool
  data: Optional[dict[str, Any]] = None
  error: Optional[ToolError] = None


def run_tool(tool_function, **arguments) -> ToolResult:
    """Run a tool and never let an exception escape: failures become ToolResult(ok=False)."""
    try:
        return ToolResult(ok=True, data=tool_function(**arguments))
    except ApplicantNotFoundError as error:
        # 1. Return a not_found error result
        return ToolResult(ok=False, error=ToolError(code="not_found", message=str(error)))
    except (CalculationInputError, ValueError, TypeError) as error:
        # 2. Return an invalid_input error result
        return ToolResult(ok=False, error=ToolError(code="invalid_input", message=str(error)))
    except Exception:
        logger.exception("tool %s failed unexpectedly", getattr(tool_function, "__name__", repr(tool_function)))
        # 3. Return an internal error result with a SAFE message
        return ToolResult(ok=False, error=ToolError(code="internal", message="The tool failed unexpectedly."))

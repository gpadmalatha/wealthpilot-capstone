"""Working memory: the live conversation, kept inside a token budget.

Policy: trim. When the conversation grows past the budget, the oldest messages
are dropped and replaced by a short note that earlier turns were removed.
Anything that must outlive trimming belongs in long-term memory, not here.
"""
import logging
from typing import Optional

from capstone.settings import get_settings

logger = logging.getLogger(__name__)

TRIM_NOTE = "[Earlier messages were removed to save space. Rely on recalled memory for older facts.]"


def estimate_tokens(text: str) -> int:
  """Cheap token estimate (about 4 characters per token). Good enough for a budget."""
  return len(text) // 4 + 1


class WorkingMemory:
  def __init__(self, system_prompt: str, budget_tokens: Optional[int] = None, min_messages: Optional[int] = None) -> None:
    settings = get_settings()
    self._system_prompt = system_prompt
    self._budget = budget_tokens if budget_tokens is not None else settings.working_memory_budget_tokens
    self._min_messages = min_messages if min_messages is not None else settings.working_memory_min_turns
    self._messages: list[dict] = []
    self.trimmed_count = 0

  def _total_tokens(self) -> int:
    return estimate_tokens(self._system_prompt) + sum(estimate_tokens(m["content"]) for m in self._messages)

  def add(self, role: str, content: str) -> None:
    self._messages.append({"role": role, "content": content})
    self._trim()

  def _trim(self) -> None:
    while self._total_tokens() > self._budget and len(self._messages) > self._min_messages:
        self._messages.pop(0)
        self.trimmed_count += 1
        logger.info("working memory trimmed one message (%d so far)", self.trimmed_count)

  def messages(self) -> list[dict]:
    """What to send to the model: system prompt, a trim note if anything was dropped, then the recent turns."""
    system = self._system_prompt + (f"\n\n{TRIM_NOTE}" if self.trimmed_count else "")
    return [{"role": "system", "content": system}, *self._messages]

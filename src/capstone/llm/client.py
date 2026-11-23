import logging
import warnings

import litellm
from litellm import completion

from capstone.settings import get_settings

logger = logging.getLogger(__name__)

litellm.suppress_debug_info = True  # no advert banners in logs
# LiteLLM message objects trigger a harmless Pydantic serializer warning on every tool turn
warnings.filterwarnings("ignore", message="Pydantic serializer warnings")


class LLMTruncatedError(Exception):
  """The model's reply was cut off by the token limit."""


def chat(messages: list[dict], *, json_mode: bool = False) -> str:
  settings = get_settings()

  kwargs = {}
  if json_mode:
        kwargs["response_format"] = {"type": "json_object"}        # BLANK 1: the JSON mode setting from Lab 1

  response = completion(
      model=settings.llm_model,
      messages=messages,
      temperature=settings.llm_temperature,
      timeout=settings.llm_timeout_seconds,
      num_retries=settings.llm_max_retries,
      **kwargs,
  )

  choice = response.choices[0]
  if choice.finish_reason == "length":
    raise LLMTruncatedError(
        f"Reply was cut off (finish_reason={choice.finish_reason}); raise the token limit."
    )
  return choice.message.content


def chat_with_tools(messages: list[dict], tools: list[dict]):
  """One model turn with tools available. Returns the assistant message (text and/or tool_calls)."""
  settings = get_settings()
  response = completion(
      model=settings.llm_model,
      messages=messages,
      tools=tools,
      temperature=settings.llm_temperature,
      timeout=settings.llm_timeout_seconds,
      num_retries=settings.llm_max_retries,
  )
  choice = response.choices[0]
  if choice.finish_reason == "length":
    raise LLMTruncatedError("Reply was cut off; raise the token limit.")
  return choice.message


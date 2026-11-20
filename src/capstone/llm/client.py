import logging

import litellm
from litellm import completion

from capstone.settings import get_settings

logger = logging.getLogger(__name__)

litellm.suppress_debug_info = True  # no advert banners in logs


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
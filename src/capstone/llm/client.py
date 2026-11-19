import logging

from litellm import completion

from capstone.settings import get_settings

logger = logging.getLogger(__name__)


class LLMTruncatedError(Exception):
  """The model's reply was cut off by the token limit."""


def chat(messages: list[dict], *, json_mode: bool = False) -> str:
  settings = get_settings()

  kwargs = {}
  if json_mode:
    kwargs["response_format"] = "JSON"          # BLANK 1: the JSON mode setting from Lab 1

  response = completion(
      model=settings.llm_model,
      messages=messages,
      temperature=settings.llm_temperature,
      timeout=settings.llm_timeout_seconds,
      **kwargs,
  )

  choice = response.choices[0]
  if choice.finish_reason ==...:             # BLANK 2: which value means "cut off"?
    raise LLMTruncatedError(...)             # BLANK 3: a clear message
  return choice.message.content
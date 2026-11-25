import logging
import time
import warnings

import litellm
from litellm import completion

from capstone.observability.tracing import annotate, traced
from capstone.settings import get_settings

logger = logging.getLogger(__name__)


def _record_usage(response) -> None:
  """Put model name and token counts on the open trace span."""
  usage = getattr(response, "usage", None)
  annotate(model=get_settings().llm_model, prompt_tokens=getattr(usage, "prompt_tokens", None), completion_tokens=getattr(usage, "completion_tokens", None))

litellm.suppress_debug_info = True  # no advert banners in logs
# LiteLLM message objects trigger a harmless Pydantic serializer warning on every tool turn
warnings.filterwarnings("ignore", message="Pydantic serializer warnings")


class LLMTruncatedError(Exception):
  """The model's reply was cut off by the token limit."""


@traced("llm.chat", kind="llm")
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

  _record_usage(response)
  choice = response.choices[0]
  if choice.finish_reason == "length":
    raise LLMTruncatedError(
        f"Reply was cut off (finish_reason={choice.finish_reason}); raise the token limit."
    )
  return choice.message.content


@traced("llm.chat_with_tools", kind="llm")
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
  _record_usage(response)
  choice = response.choices[0]
  if choice.finish_reason == "length":
    raise LLMTruncatedError("Reply was cut off; raise the token limit.")
  return choice.message


@traced("llm.embed", kind="llm")
def embed(texts: list[str]) -> list[list[float]]:
  """Embed texts with the configured embedding model (provider-agnostic, via LiteLLM)."""
  settings = get_settings()
  for attempt in range(1, settings.embedding_rate_limit_retries + 2):
    try:
      response = litellm.embedding(
          model=settings.embedding_model,
          input=texts,
          timeout=settings.llm_timeout_seconds,
      )
      return [item["embedding"] for item in response.data]
    except litellm.RateLimitError:
      if attempt > settings.embedding_rate_limit_retries:
        raise
      logger.warning("embedding rate limit hit; waiting %.0fs (retry %d)", settings.embedding_retry_wait_seconds, attempt)
      time.sleep(settings.embedding_retry_wait_seconds)
  raise RuntimeError("unreachable")


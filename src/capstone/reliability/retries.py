"""Bounded retries with exponential backoff and jitter. Only errors marked retryable are retried."""
import logging
import random
import time
from typing import Callable, Optional, TypeVar

from capstone.observability.tracing import annotate
from capstone.settings import get_settings

logger = logging.getLogger(__name__)
T = TypeVar("T")


class SourceUnavailableError(Exception):
  """A dependency timed out or is down. Worth retrying."""


def call_with_retries(
    function: Callable[[], T],
    *,
    retryable: tuple[type[Exception], ...] = (SourceUnavailableError, TimeoutError, ConnectionError),
    max_attempts: Optional[int] = None,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = random.random,
    label: str = "call",
) -> T:
  """Run function up to max_attempts times. The last error is re-raised; non-retryable errors are not retried."""
  settings = get_settings()
  attempts = max_attempts or settings.retry_max_attempts
  for attempt in range(1, attempts + 1):
    try:
      result = function()
      annotate(retries=attempt - 1)  # on the open trace span: how many retries this call needed
      return result
    except retryable as error:
      if attempt == attempts:
        annotate(retries=attempt - 1)
        logger.warning("%s failed after %d attempts: %s", label, attempts, error)
        raise
      delay = min(settings.retry_base_delay_seconds * (2 ** (attempt - 1)), settings.retry_max_delay_seconds)
      delay += jitter() * settings.retry_base_delay_seconds  # jitter stops many callers retrying in lockstep
      logger.warning("%s failed (attempt %d of %d): %s; retrying in %.2fs", label, attempt, attempts, error, delay)
      sleep(delay)
  raise RuntimeError("unreachable")
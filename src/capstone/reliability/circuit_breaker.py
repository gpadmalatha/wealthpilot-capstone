"""Circuit breaker: after repeated failures stop calling a dependency for a cool-down, then allow one trial call."""
import logging
import threading
import time
from typing import Callable, Optional, TypeVar

from capstone.settings import get_settings

logger = logging.getLogger(__name__)
T = TypeVar("T")

CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"


class CircuitOpenError(Exception):
  """The breaker is open: the call was refused without touching the dependency."""


class CircuitBreaker:
  def __init__(self, name: str, *, failure_threshold: Optional[int] = None, reset_seconds: Optional[float] = None,
               clock: Callable[[], float] = time.monotonic):
    settings = get_settings()
    self.name = name
    self.failure_threshold = failure_threshold or settings.breaker_failure_threshold
    self.reset_seconds = settings.breaker_reset_seconds if reset_seconds is None else reset_seconds
    self._clock = clock
    self._lock = threading.Lock()
    self._failures = 0
    self._opened_at = 0.0
    self._state = CLOSED
    self._trial_in_flight = False

  @property
  def state(self) -> str:
    with self._lock:
      return self._current_state()

  def _current_state(self) -> str:
    if self._state == OPEN and self._clock() - self._opened_at >= self.reset_seconds:
      self._state = HALF_OPEN
    return self._state

  def call(self, function: Callable[[], T], *, counts_as_failure: tuple[type[Exception], ...] = (Exception,)) -> T:
    with self._lock:
      state = self._current_state()
      if state == OPEN or (state == HALF_OPEN and self._trial_in_flight):
        raise CircuitOpenError(f"Circuit '{self.name}' is open.")
      if state == HALF_OPEN:
        self._trial_in_flight = True
    try:
      result = function()
    except counts_as_failure:
      self._record_failure()
      raise
    except Exception:  # an error that is not a dependency failure (for example bad input) leaves the breaker alone
      with self._lock:
        self._trial_in_flight = False
      raise
    self._record_success()
    return result

  def _record_failure(self) -> None:
    with self._lock:
      self._trial_in_flight = False
      self._failures += 1
      if self._state == HALF_OPEN or self._failures >= self.failure_threshold:
        if self._state != OPEN:
          logger.warning("circuit '%s' opened after %d failures", self.name, self._failures)
        self._state = OPEN
        self._opened_at = self._clock()

  def _record_success(self) -> None:
    with self._lock:
      if self._state != CLOSED:
        logger.info("circuit '%s' closed again", self.name)
      self._state = CLOSED
      self._failures = 0
      self._trial_in_flight = False

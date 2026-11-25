"""Keep unit tests away from real runtime files: traces, bureau cache and breaker state are isolated per test."""
import pytest

from capstone.observability import tracing
from capstone.reliability import fallbacks


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
  monkeypatch.setattr(fallbacks, "_default_cache_path", lambda: tmp_path / "bureau_cache.json")
  monkeypatch.setattr(fallbacks, "_default", None)
  tracing.set_sink(lambda event: None)
  yield
  tracing.set_sink(None)

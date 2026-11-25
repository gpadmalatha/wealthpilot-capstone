"""Keep unit tests away from real runtime files: traces, bureau cache and breaker state are isolated per test."""
from pathlib import Path

import pytest

from capstone.memory import long_term
from capstone.observability import tracing
from capstone.reliability import fallbacks


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
  monkeypatch.setattr(fallbacks, "_default_cache_path", lambda: tmp_path / "bureau_cache.json")
  monkeypatch.setattr(fallbacks, "_default", None)
  monkeypatch.setattr(long_term, "default_db_path", lambda: tmp_path / "memory.db")
  tracing.set_sink(lambda event: None)
  yield
  tracing.set_sink(None)


def pytest_sessionstart(session):
  """The toolkit data is git-ignored; stop with one clear message instead of dozens of file errors."""
  root = Path(__file__).resolve().parents[2]
  needed = root / "data" / "wealthpilot" / "mock_api" / "applicants.csv"
  if not needed.exists():
    pytest.exit(
      "Toolkit data not found at data/wealthpilot/. It is git-ignored: generate it with the course "
      "Data Toolkit (python generate.py --domain wealthpilot) and copy the output there. "
      "See docs/data_sources.md.",
      returncode=2,
    )

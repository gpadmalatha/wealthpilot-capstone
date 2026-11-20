"""Shared test setup: a model name must exist for Settings, but no test calls a real model."""
import os

os.environ.setdefault("LLM_MODEL", "test/offline-model")

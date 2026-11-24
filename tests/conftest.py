"""Shared test setup: model names must exist for Settings, but no test calls a real model."""
import os

os.environ.setdefault("LLM_MODEL", "test/offline-model")
os.environ.setdefault("EMBEDDING_MODEL", "test/offline-embedding")

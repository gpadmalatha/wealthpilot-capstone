"""Durable checkpoints: workflow state lives in SQLite, so an interrupted run survives a restart."""
import sqlite3
from pathlib import Path
from typing import Optional

from langgraph.checkpoint.sqlite import SqliteSaver

from capstone.settings import get_settings


def default_checkpoint_path() -> Path:
  folder = get_settings().project_root / "runtime" / "checkpoints"
  folder.mkdir(parents=True, exist_ok=True)
  return folder / "workflow.db"


def open_checkpointer(path: Optional[Path] = None) -> SqliteSaver:
  connection = sqlite3.connect(path or default_checkpoint_path(), check_same_thread=False)
  return SqliteSaver(connection)

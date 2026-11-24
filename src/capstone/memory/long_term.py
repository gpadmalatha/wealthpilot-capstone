"""Persistent, namespaced long-term memory: episodic, semantic and procedural records.

Every record belongs to one applicant (its namespace). All reads go through
_select(), so the namespace filter lives in exactly one place.
"""
import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from capstone.settings import get_settings

logger = logging.getLogger(__name__)

KINDS = ("episodic", "semantic", "procedural")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  applicant_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('episodic', 'semantic', 'procedural')),
  key TEXT,
  content TEXT NOT NULL,
  session_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_namespace ON memories (applicant_id, kind);
"""


def default_db_path() -> Path:
  folder = get_settings().project_root / "runtime" / "memory"
  folder.mkdir(parents=True, exist_ok=True)
  return folder / "memory.db"


def _now() -> str:
  return datetime.now(timezone.utc).isoformat()


class MemoryStore:
  """SQLite-backed store. A new MemoryStore on the same file sees everything saved before."""

  def __init__(self, db_path: Optional[Path] = None) -> None:
    self._db_path = db_path or default_db_path()
    with closing(self._connect()) as connection, connection:
      connection.executescript(_SCHEMA)

  def _connect(self) -> sqlite3.Connection:
    connection = sqlite3.connect(self._db_path)
    connection.row_factory = sqlite3.Row
    return connection

  def _select(self, applicant_id: str, kind: str) -> list[dict]:
    """The only read path. Returns this applicant's records of one kind, newest first."""
    if kind not in KINDS:
      raise ValueError(f"kind must be one of {KINDS}")
    with closing(self._connect()) as connection:
            rows = connection.execute(
          "SELECT * FROM memories WHERE applicant_id = ? AND kind = ? "
          "ORDER BY updated_at DESC, id DESC",
          (applicant_id, kind),
      ).fetchall()
    return [dict(row) for row in rows]

  def add_event(self, applicant_id: str, session_id: str, content: str) -> None:
    """Episodic: append something that happened, stamped with time and session."""
    now = _now()
    with closing(self._connect()) as connection, connection:
      connection.execute(
          "INSERT INTO memories (applicant_id, kind, key, content, session_id, created_at, updated_at) "
          "VALUES (?, 'episodic', NULL, ?, ?, ?, ?)",
          (applicant_id, content, session_id, now, now),
      )

  def _save_keyed(self, applicant_id: str, kind: str, key: str, content: str, session_id: Optional[str]) -> None:
    """Semantic and procedural: one record per (applicant, kind, key). Saving again updates it."""
    now = _now()
    with closing(self._connect()) as connection, connection:
      existing = connection.execute(
          "SELECT id FROM memories WHERE applicant_id = ? AND kind = ? AND key = ?",
          (applicant_id, kind, key),
      ).fetchone()
      if existing is not None:
         connection.execute(
            "UPDATE memories SET content = ?, session_id = ?, updated_at = ? WHERE id = ?",
            (content, session_id, now, existing["id"]),
        )
      else:
        connection.execute(
            "INSERT INTO memories (applicant_id, kind, key, content, session_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (applicant_id, kind, key, content, session_id, now, now),
        )

  def save_fact(self, applicant_id: str, key: str, content: str, session_id: Optional[str] = None) -> None:
    """Semantic: a stable fact such as sector or location. A changed fact replaces the old one."""
    self._save_keyed(applicant_id, "semantic", key, content, session_id)

  def save_procedure(self, applicant_id: str, key: str, content: str, session_id: Optional[str] = None) -> None:
    """Procedural: a how-to the agent should follow. Saving the same key updates the procedure."""
    self._save_keyed(applicant_id, "procedural", key, content, session_id)

  def recall(self, applicant_id: str, kind: str, query: Optional[str] = None, limit: int = 5) -> list[dict]:
    """Records of one kind for one applicant. With a query, best word-overlap first."""
    records = self._select(applicant_id, kind)
    if query:
      words = {word for word in query.lower().split() if len(word) > 2}
      def overlap(record: dict) -> int:
        text = f"{record['key'] or ''} {record['content']}".lower()
        return sum(1 for word in words if word in text)
      records = sorted(records, key=overlap, reverse=True)
    return records[:limit]

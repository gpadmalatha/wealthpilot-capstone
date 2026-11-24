"""Offline tests for long-term memory: persistence, update rule, isolation."""
from capstone.memory.long_term import MemoryStore


def make(tmp_path):
  return MemoryStore(tmp_path / "memory.db")


def test_fact_survives_restart(tmp_path):
  make(tmp_path).save_fact("A-1", "location", "Tiruppur textile SME")
  facts = make(tmp_path).recall("A-1", "semantic")  # a brand-new store object = a restart
  assert facts[0]["content"] == "Tiruppur textile SME"


def test_changed_fact_replaces_old_one(tmp_path):
  store = make(tmp_path)
  store.save_fact("A-1", "location", "Tiruppur")
  store.save_fact("A-1", "location", "Coimbatore")
  facts = store.recall("A-1", "semantic")
  assert len(facts) == 1 and facts[0]["content"] == "Coimbatore"


def test_applicant_b_sees_nothing_of_a(tmp_path):
  store = make(tmp_path)
  store.save_fact("A-1", "location", "Tiruppur")
  store.add_event("A-1", "s1", "Requested six months of statements")
  store.save_procedure("A-1", "scoring", "Check sector note thresholds first")
  for kind in ("semantic", "episodic", "procedural"):
    assert store.recall("B-2", kind) == []


def test_event_recalled_in_a_new_session_with_time_and_session(tmp_path):
  store = make(tmp_path)
  store.add_event("A-1", "s1", "Requested six months of statements, DSCR computed")
  events = make(tmp_path).recall("A-1", "episodic")
  assert events[0]["session_id"] == "s1" and events[0]["created_at"]


def test_procedure_is_updatable(tmp_path):
  store = make(tmp_path)
  store.save_procedure("A-1", "scoring", "Check sector thresholds")
  store.save_procedure("A-1", "scoring", "Check sector thresholds, then bureau policy")
  procedures = store.recall("A-1", "procedural")
  assert len(procedures) == 1 and "bureau" in procedures[0]["content"]


def test_query_ranks_by_word_overlap(tmp_path):
  store = make(tmp_path)
  store.save_fact("A-1", "sector", "Textiles")
  store.save_fact("A-1", "location", "Tiruppur")
  assert store.recall("A-1", "semantic", query="which location", limit=1)[0]["key"] == "location"


def test_unknown_kind_is_rejected(tmp_path):
  import pytest
  with pytest.raises(ValueError):
    make(tmp_path).recall("A-1", "dreams")

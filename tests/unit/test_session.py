"""Offline tests for working-memory trimming."""
from capstone.memory.session import TRIM_NOTE, WorkingMemory


def test_short_conversation_is_untouched():
  memory = WorkingMemory("You are a helper.", budget_tokens=500, min_messages=2)
  memory.add("user", "hello")
  memory.add("assistant", "hi")
  assert len(memory.messages()) == 3 and memory.trimmed_count == 0


def test_long_conversation_is_trimmed_oldest_first():
  memory = WorkingMemory("sys", budget_tokens=60, min_messages=2)
  for turn in range(15):
    memory.add("user", f"filler turn number {turn} " + "x" * 40)
  contents = [m["content"] for m in memory.messages()[1:]]
  assert memory.trimmed_count > 0
  assert "turn number 0 " not in " ".join(contents)
  assert "turn number 14 " in contents[-1]


def test_never_trims_below_minimum_recent_messages():
  memory = WorkingMemory("sys", budget_tokens=1, min_messages=3)
  for turn in range(10):
    memory.add("user", f"message {turn} " + "y" * 200)
  assert len(memory.messages()) == 1 + 3


def test_trim_note_appears_only_after_trimming():
  memory = WorkingMemory("sys", budget_tokens=500, min_messages=2)
  memory.add("user", "hello")
  assert TRIM_NOTE not in memory.messages()[0]["content"]
  small = WorkingMemory("sys", budget_tokens=10, min_messages=1)
  small.add("user", "a" * 100)
  small.add("user", "b" * 100)
  assert TRIM_NOTE in small.messages()[0]["content"]

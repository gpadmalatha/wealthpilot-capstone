"""Offline tests for the memory agent: namespace set by code, recall into the prompt, event logging."""
import json
from types import SimpleNamespace

from capstone.agents import underwriting_agent
from capstone.agents.memory_agent import MemoryAgent
from capstone.memory.long_term import MemoryStore


def call(name, arguments, call_id="c1"):
  return SimpleNamespace(content=None, tool_calls=[SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))])


def say(text):
  return SimpleNamespace(content=text, tool_calls=None)


def script(monkeypatch, replies, seen=None):
  iterator = iter(replies)

  def fake(messages, tools):
    if seen is not None:
      seen.append({"messages": list(messages), "tools": tools})
    return next(iterator)
  monkeypatch.setattr(underwriting_agent, "chat_with_tools", fake)


def make_agent(tmp_path, applicant="A-1", session="s1"):
  return MemoryAgent(applicant, session, MemoryStore(tmp_path / "m.db"))


def test_memory_tools_do_not_expose_applicant_id(tmp_path):
  _, specs = make_agent(tmp_path)._memory_tools()
  for spec in specs:
    assert "applicant" not in json.dumps(spec["function"]["parameters"])


def test_model_saved_fact_lands_in_the_sessions_namespace(tmp_path, monkeypatch):
  script(monkeypatch, [call("remember_fact", {"key": "location", "content": "Tiruppur"}), say("Noted.")])
  agent = make_agent(tmp_path, "A-1")
  agent.turn("We are in Tiruppur.")
  store = MemoryStore(tmp_path / "m.db")
  assert store.recall("A-1", "semantic")[0]["content"] == "Tiruppur"
  assert store.recall("B-2", "semantic") == []


def test_prohibited_key_is_rejected_and_nothing_stored(tmp_path, monkeypatch):
  script(monkeypatch, [call("remember_fact", {"key": "religion", "content": "x"}), say("I cannot store that.")])
  agent = make_agent(tmp_path)
  run = agent.turn("Remember my religion.")
  assert run.tool_calls[0].result.error.code == "invalid_input"
  assert MemoryStore(tmp_path / "m.db").recall("A-1", "semantic") == []


def test_new_session_prompt_contains_own_memory_only(tmp_path, monkeypatch):
  store = MemoryStore(tmp_path / "m.db")
  store.save_fact("A-1", "location", "Tiruppur")
  store.save_procedure("A-1", "scoring", "Check sector note thresholds first")
  store.add_event("A-1", "s1", "Called assess_dscr: ok")
  prompt_a = MemoryAgent("A-1", "s2", store).build_system_prompt()
  prompt_b = MemoryAgent("B-2", "s9", store).build_system_prompt()
  assert "Tiruppur" in prompt_a and "sector note thresholds" in prompt_a and "assess_dscr" in prompt_a
  assert "Tiruppur" not in prompt_b and "Nothing is stored yet" in prompt_b


def test_tool_use_is_logged_as_an_event_by_code(tmp_path, monkeypatch):
  script(monkeypatch, [call("assess_dscr", {"application_id": "ASH-L-00000"}), say("Done.")])
  agent = make_agent(tmp_path, "ASH-A-00000")
  agent.turn("Compute the DSCR.")
  events = MemoryStore(tmp_path / "m.db").recall("ASH-A-00000", "episodic")
  assert "assess_dscr" in events[0]["content"] and "dscr=" in events[0]["content"] and events[0]["session_id"] == "s1"


def test_turns_enter_working_memory_and_are_passed_as_history(tmp_path, monkeypatch):
  seen = []
  script(monkeypatch, [say("Hello."), say("Fine.")], seen)
  agent = make_agent(tmp_path)
  agent.turn("hi")
  agent.turn("how are you")
  history = [m["content"] for m in seen[1]["messages"][1:-1]]
  assert history == ["hi", "Hello."]

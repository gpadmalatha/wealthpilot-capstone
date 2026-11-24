"""Memory-enabled agent: recalled memory goes into every turn, and the namespace is set by code.

The model can save facts and procedures, but the memory tools it sees have no applicant
parameter: the applicant_id is bound here, from the session, never chosen by the model.
"""
import logging
from typing import Optional

from capstone.agents.underwriting_agent import AgentRun, ToolCallRecord, load_prompt, run_agent
from capstone.memory.long_term import MemoryStore
from capstone.memory.session import WorkingMemory
from capstone.tools.registry import build_spec

logger = logging.getLogger(__name__)

# Tools whose use is worth remembering as an event, logged by code after they run.
EVENT_TOOLS = ("get_bank_statements", "assess_dscr", "check_bureau_policy", "hand_off_to_human")
# Fair lending: names, community, language and postal codes are proxies and are never stored.
PROHIBITED_KEY_PARTS = ("name", "religion", "community", "caste", "language", "postal", "pincode", "pin_code", "gender")
RECALLED_FACTS = 20
RECALLED_PROCEDURES = 10
RECALLED_EVENTS = 5


class MemoryAgent:
  def __init__(self, applicant_id: str, session_id: str, store: Optional[MemoryStore] = None, budget_tokens: Optional[int] = None) -> None:
    self.applicant_id = applicant_id
    self.session_id = session_id
    self.store = store or MemoryStore()
    self._base_prompt = load_prompt("m2_agent.md") + "\n" + load_prompt("memory_rules.md")
    self.working = WorkingMemory(self._base_prompt, budget_tokens=budget_tokens)

  def _memory_tools(self) -> tuple[dict, list[dict]]:
    store, applicant_id, session_id = self.store, self.applicant_id, self.session_id

    def check_key(key: str) -> None:
      lowered = key.lower()
      if any(part in lowered for part in PROHIBITED_KEY_PARTS):
        raise ValueError(f"Key '{key}' is not allowed: fair-lending rules forbid storing name, religion, community, language or postal code.")

    def remember_fact(key: str, content: str) -> dict:
      """Save a stable fact about this applicant's business, such as sector or location, for later sessions.

      Use when the applicant states something that stays true. Use a short snake_case key; saving the same key
      again replaces the old value. Do not use for one-off events, and never for name, religion, community,
      language or postal code.
      """
      check_key(key)
      store.save_fact(applicant_id, key, content, session_id)
      return {"saved": key, "content": content}

    def remember_procedure(key: str, content: str) -> dict:
      """Save a procedure the applicant or analyst wants followed from now on, for example a check to do before scoring.

      Use only when asked to follow a standing procedure. Saving the same key again updates the procedure.
      Do not use for facts or one-off events.
      """
      check_key(key)
      store.save_procedure(applicant_id, key, content, session_id)
      return {"saved": key, "content": content}

    functions = {"remember_fact": remember_fact, "remember_procedure": remember_procedure}
    key_schema = {"type": "string", "description": "Short snake_case key, for example sector or location"}
    specs = [
        build_spec(remember_fact, {"key": key_schema, "content": {"type": "string"}}, ["key", "content"]),
        build_spec(remember_procedure, {"key": key_schema, "content": {"type": "string"}}, ["key", "content"]),
    ]
    return functions, specs

  def build_system_prompt(self, query: str = "") -> str:
    """Base prompt plus what is remembered for THIS applicant only (every read is namespaced)."""
    facts = self.store.recall(self.applicant_id, "semantic", query or None, RECALLED_FACTS)
    procedures = self.store.recall(self.applicant_id, "procedural", query or None, RECALLED_PROCEDURES)
    events = self.store.recall(self.applicant_id, "episodic", None, RECALLED_EVENTS)
    if not (facts or procedures or events):
      return self._base_prompt + "\n\n## Remembered about this applicant\nNothing is stored yet."
    lines = ["", "## Remembered about this applicant"]
    if facts:
      lines += ["Facts:"] + [f"- {f['key']}: {f['content']}" for f in facts]
    if procedures:
      lines += ["Procedures to follow:"] + [f"- {p['key']}: {p['content']}" for p in procedures]
    if events:
      lines += ["Recent events (newest first):"] + [f"- {e['created_at'][:10]} (session {e['session_id']}): {e['content']}" for e in events]
    return self._base_prompt + "\n" + "\n".join(lines)

  def _log_event(self, record: ToolCallRecord) -> None:
    if record.name not in EVENT_TOOLS:
      return
    if record.result.ok:
      data = record.result.data or {}
      detail = ", ".join(f"{k}={data[k]}" for k in ("dscr", "meets_floor", "months_returned", "shortfall_months", "score_is_adverse", "required_authority") if k in data)
      outcome = f"ok ({detail})" if detail else "ok"
    else:
      outcome = f"error {record.result.error.code}"
    self.store.add_event(self.applicant_id, self.session_id, f"Called {record.name} with {record.arguments}: {outcome}")

  def turn(self, text: str) -> AgentRun:
    functions, specs = self._memory_tools()
    run = run_agent(
        text,
        system_prompt=self.build_system_prompt(text),
        history=self.working.messages()[1:],
        extra_functions=functions,
        extra_specs=specs,
        on_tool_call=self._log_event,
    )
    self.working.add("user", text)
    self.working.add("assistant", run.answer or "(no answer)")
    return run

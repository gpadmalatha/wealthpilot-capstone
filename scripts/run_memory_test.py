"""Memory test T1-T9 for WealthPilot. Two phases run as two separate Python processes, so the restart is real.

Usage: python scripts/run_memory_test.py            (runs phase 1, a restart, then phase 2)
Evidence is written to docs/m3_memory_test.txt. The test uses its own database, not the real one.
"""
import logging
import subprocess
import sys
import time

from capstone.agents.memory_agent import MemoryAgent
from capstone.memory.long_term import MemoryStore
from capstone.settings import get_settings

APPLICANT_A = "ASH-A-00000"
APPLICANT_B = "ASH-A-00001"
FILLER_TURNS = 16


def _paths():
  root = get_settings().project_root
  return root / "runtime" / "memory" / "memory_test.db", root / "docs" / "m3_memory_test.txt"


def _record(report, name, passed, detail):
  line = f"{name} {'PASS' if passed else 'FAIL'}: {detail}"
  report.write_text(report.read_text(encoding="utf-8") + line + "\n", encoding="utf-8")
  print(line)


def _ask(agent, text):
  run = agent.turn(text)
  time.sleep(get_settings().eval_delay_seconds)
  return run, (run.answer or "").replace("\n", " ")


def phase1():
  db, report = _paths()
  db.unlink(missing_ok=True)
  report.write_text(f"model: {get_settings().llm_model}\nPHASE 1 (session s1, applicant {APPLICANT_A})\n", encoding="utf-8")
  agent = MemoryAgent(APPLICANT_A, "s1", MemoryStore(db))

  _ask(agent, "We are a textile SME based in Tiruppur.")
  facts = agent.store.recall(APPLICANT_A, "semantic")
  _record(report, "T1 fact stored", any("tiruppur" in f["content"].lower() for f in facts), [f"{f['key']}={f['content']}" for f in facts])

  _ask(agent, "Please request six months of bank statements for application ASH-L-00000 and compute the DSCR.")
  events = " | ".join(e["content"] for e in agent.store.recall(APPLICANT_A, "episodic"))
  _record(report, "T2 event logged", "get_bank_statements" in events and "assess_dscr" in events, events[:300])

  _ask(agent, "From now on, always check the sector note thresholds before scoring. Please remember that procedure.")
  procedures = agent.store.recall(APPLICANT_A, "procedural")
  _record(report, "T3 procedure stored", any("threshold" in p["content"].lower() for p in procedures), [f"{p['key']}={p['content']}" for p in procedures])
  report.write_text(report.read_text(encoding="utf-8") + "-- process restart --\n", encoding="utf-8")


def phase2():
  db, report = _paths()
  report.write_text(report.read_text(encoding="utf-8") + f"PHASE 2 (new process, new sessions)\n", encoding="utf-8")
  store = MemoryStore(db)
  agent = MemoryAgent(APPLICANT_A, "s2", store)

  _, answer = _ask(agent, "Where is my business based?")
  _record(report, "T4 recall fact after restart", "tiruppur" in answer.lower(), answer[:200])

  _, answer = _ask(agent, "What did we do on my application last time?")
  _record(report, "T5 recall episode", ("bank statement" in answer.lower() or "dscr" in answer.lower()), answer[:200])

  _, answer = _ask(agent, "Time to score my application ASH-L-00000. Which steps will you take, in order?")
  _record(report, "T6 procedure applied", "threshold" in answer.lower() and "sector" in answer.lower(), answer[:200])

  _, _ = _ask(agent, "Actually we have moved our unit to Coimbatore.")
  _, answer = _ask(agent, "Where is my business based now?")
  locations = [f["content"] for f in store.recall(APPLICANT_A, "semantic") if "coimbatore" in f["content"].lower() or "tiruppur" in f["content"].lower()]
  _record(report, "T7 changed fact replaced", len(locations) == 1 and "coimbatore" in locations[0].lower() and "coimbatore" in answer.lower(), f"stored={locations}; answer={answer[:150]}")

  agent_b = MemoryAgent(APPLICANT_B, "s3", store)
  _, answer = _ask(agent_b, "Where is my business based, and what did we do last time?")
  leaked = any(word in answer.lower() for word in ("tiruppur", "coimbatore"))
  empty = all(store.recall(APPLICANT_B, kind) == [] for kind in ("semantic", "episodic", "procedural"))
  _record(report, "T8 applicant B sees nothing of A", not leaked and empty, answer[:200])

  agent_c = MemoryAgent(APPLICANT_A, "s4", store, budget_tokens=400)
  for turn in range(FILLER_TURNS):
    _ask(agent_c, f"Filler turn {turn + 1}: please reply with just the word OK.")
  _, answer = _ask(agent_c, "Which city is my business in?")
  _record(report, "T9 recall after filler turns", agent_c.working.trimmed_count > 0 and "coimbatore" in answer.lower(),
          f"trimmed_messages={agent_c.working.trimmed_count}; answer={answer[:150]}")


def main() -> None:
  logging.basicConfig(level=logging.WARNING)
  if len(sys.argv) > 1:
    {"phase1": phase1, "phase2": phase2}[sys.argv[1]]()
    return
  for phase in ("phase1", "phase2"):
    subprocess.run([sys.executable, __file__, phase], check=True)


if __name__ == "__main__":
  main()

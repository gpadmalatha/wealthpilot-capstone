"""Evidence run: the workflow graph uses the registered tools and long-term memory. No model calls.

Run:  python scripts\run_workflow_memory.py     Writes docs/m5_workflow_memory_run.txt.
Shows (1) the tools each run used, (2) the outcome remembered per applicant and recalled by a new store on the
same file, (3) a standing procedure that sends an auto-approvable case to a human, and (4) that memory is per applicant.
"""
from datetime import datetime

from capstone.agents.intake_agent import load_application
from capstone.memory.long_term import MemoryStore
from capstone.settings import get_settings
from capstone.tools import actions
from capstone.tools.policy_engine import assess_application
from capstone.tools.repository import get_repository
from capstone.workflows import graph as wf
from capstone.workflows.checkpoints import open_checkpointer

lines: list[str] = []


def say(text: str = "") -> None:
  print(text)
  lines.append(text)


def tools_used(result: dict) -> str:
  return ", ".join(f"{c['tool']}{'' if c['ok'] else ' (failed: ' + str(c['error']) + ')'}" for c in result["tool_calls"])


def auto_approvable(count: int) -> list[str]:
  found = []
  for application_id in get_repository().applications:
    if assess_application(application_id)["auto_approve_allowed"]:
      found.append(application_id)
      if len(found) == count:
        break
  return found


def main() -> None:
  settings = get_settings()
  folder = settings.project_root / "runtime" / f"m5_memory_{datetime.now():%Y%m%d_%H%M%S}"
  folder.mkdir(parents=True, exist_ok=True)
  actions._decision_file = lambda: folder / "decisions.jsonl"
  store = MemoryStore(folder / "memory.db")
  graph = wf.build_graph(open_checkpointer(folder / "workflow.db"), memory=store)
  first, second = auto_approvable(2)
  owner_first, owner_second = load_application(first).applicant_id, load_application(second).applicant_id

  say(f"1. A routine application ({first}, applicant {owner_first}) with nothing remembered yet")
  result = wf.start(graph, first)
  say(f"   trail: {result['trail']}")
  say(f"   tools: {tools_used(result)}")
  say(f"   outcome={result['outcome']} decided_by={result['decision']['decided_by']}")

  say("")
  say("2. What was remembered, read back by a NEW store on the same database file (as after a restart)")
  fresh = MemoryStore(folder / "memory.db")
  for event in fresh.recall(owner_first, "episodic"):
    say(f"   event: {event['content']}")
  for fact in fresh.recall(owner_first, "semantic"):
    say(f"   fact:  {fact['key']} = {fact['content']}")

  say("")
  say(f"3. An analyst saves a standing procedure for applicant {owner_second}; their routine application {second} would normally be approved automatically")
  store.save_procedure(owner_second, "always_human_review", "Analyst asked for manual review of this applicant.")
  result = wf.start(graph, second)
  say(f"   trail: {result['trail']}")
  request = result["request"]
  say(f"   status={result['status']} review kind={request['kind']} required authority={request['required_authority']}")
  say(f"   memory hold shown to the reviewer: {request['memory']['hold']}")
  say(f"   decided automatically? {'yes' if (folder / 'decisions.jsonl').read_text().count(second) else 'no'}")
  result = wf.resume(graph, second, {"outcome": "approved", "decided_by": "ASH-U-001", "note": "Reviewed manually; standards met."})
  say(f"   after the reviewer answers: outcome={result['outcome']} decided_by={result['decision']['decided_by']}")

  say("")
  say("4. Memory is per applicant")
  say(f"   events stored for {owner_first}: {len(fresh.recall(owner_first, 'episodic'))}; for {owner_second}: {len(fresh.recall(owner_second, 'episodic'))}")
  say("   each applicant's memory holds only that applicant's own record")
  say("")
  say("Rule: memory can only send a case to a human. It never approves, declines or relaxes a policy check.")

  report = settings.project_root / "docs" / "m5_workflow_memory_run.txt"
  report.write_text("\n".join(lines) + "\n", encoding="utf-8")
  print(f"\nSaved {report}")


if __name__ == "__main__":
  main()

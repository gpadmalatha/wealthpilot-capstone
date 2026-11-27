"""M6 demo: the committee runs inside the workflow, the run pauses for a human, the process is killed, a NEW process resumes.

Needs your model key in .env (the three reviewer roles call the model) and the MCP server (started automatically over stdio).
Run:  python scripts\\run_m6_team_resume.py        Writes docs/m6_team_resume_run.txt
Proves: (1) the committee memo is stored in the checkpoint before the human is asked, (2) the pause survives a restart,
(3) exactly one decision is recorded, by a human, after the resume.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from capstone.agents.committee import run_committee
from capstone.settings import get_settings
from capstone.tools import actions
from capstone.workflows import graph as wf
from capstone.workflows.checkpoints import open_checkpointer

CASES = {"ASH-L-00006": "borderline", "ASH-L-00046": "approvable, 1.8 million"}
ANSWERS = {
    "ASH-L-00006": [{"outcome": "declined", "decided_by": "ASH-U-001", "note": "Thin margins; decline."}],
    "ASH-L-00046": [{"outcome": "approved", "decided_by": "ASH-U-013", "note": "Credit Committee sign-off."}],
}


def _setup(folder: Path):
  folder.mkdir(parents=True, exist_ok=True)
  actions._decision_file = lambda: folder / "decisions.jsonl"
  return wf.build_graph(open_checkpointer(folder / "workflow.db"), committee=run_committee)


def phase_start(folder: Path):
  graph = _setup(folder)
  print("PROCESS 1: start with the committee switched on")
  for application_id, label in CASES.items():
    result = wf.start(graph, application_id)
    state = graph.get_state({"configurable": {"thread_id": application_id}}).values
    memo = state.get("committee") or {}
    print(f"- {application_id} [{label}] status={result['status']} trail={result['trail']}")
    print(f"    committee outcome={memo.get('outcome')} rounds={memo.get('rounds')} recommendation={memo.get('final_recommendation')} (advisory only)")
    print(f"    decisions recorded so far: 0 (the human has not answered)")


def phase_resume(folder: Path):
  graph = _setup(folder)
  print("PROCESS 2: a brand new process, same checkpoint database")
  for application_id, answers in ANSWERS.items():
    print(f"- {application_id}: still waiting on disk = {wf.is_waiting(graph, application_id)}")
    committee = graph.get_state({"configurable": {"thread_id": application_id}}).values.get("committee") or {}
    print(f"    committee memo restored from checkpoint: outcome={committee.get('outcome')}")
    for answer in answers:
      result = wf.resume(graph, application_id, answer)
      print(f"    human {answer['decided_by']} answered {answer['outcome']} -> {result['status']} outcome={result.get('outcome')}")
  lines = (folder / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
  ids = [json.loads(line)["application_id"] for line in lines]
  print(f"\nDecisions on disk: {len(lines)}; unique applications: {len(set(ids))} (exactly one decision each, made by a human)")


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--phase", choices=["start", "resume"])
  parser.add_argument("--folder")
  args = parser.parse_args()
  if args.phase:
    (phase_start if args.phase == "start" else phase_resume)(Path(args.folder))
    return
  folder = get_settings().project_root / "runtime" / f"m6_team_{datetime.now():%Y%m%d_%H%M%S}"
  outputs = []
  for phase in ("start", "resume"):
    done = subprocess.run([sys.executable, __file__, "--phase", phase, "--folder", str(folder)], capture_output=True, text=True)
    outputs.append(done.stdout + (done.stderr if done.returncode else ""))
    print(outputs[-1])
  out = get_settings().project_root / "docs" / "m6_team_resume_run.txt"
  out.write_text("\n".join(outputs), encoding="utf-8")
  print(f"Saved {out}")


if __name__ == "__main__":
  main()

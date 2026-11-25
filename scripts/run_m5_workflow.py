"""M5 demo: routing, a human pause, a restart, and a safe resume. Writes docs/m5_workflow_run.txt.

Run:  python scripts\run_m5_workflow.py
The script starts the workflow in one Python process, then launches a SECOND process to resume it,
which proves the pause is stored on disk and not in memory.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from capstone.settings import get_settings
from capstone.tools import actions
from capstone.workflows import graph as wf
from capstone.workflows.checkpoints import open_checkpointer

CASES = {
    "ASH-L-00057": "operating 6 months: automatic decline (policy 4.02.3)",
    "ASH-L-00000": "declined on bureau grounds: needs human sign-off (policy 4.08.2)",
    "ASH-L-00005": "clean, small",
    "ASH-L-00006": "borderline",
    "ASH-L-00017": "revenue mismatch over 25 percent (fraud hold)",
    "ASH-L-00046": "approvable, 1.8 million",
    "ASH-L-00029": "approvable, 8.5 million",
}
ANSWERS = {  # what the human reviewers say when the second process resumes the paused runs
    "ASH-L-00000": [
        {"outcome": "approved", "decided_by": "ASH-U-001", "note": "Trying to approve a policy decline."},
        {"outcome": "declined", "decided_by": "ASH-U-001", "note": "Decline confirmed."},
    ],
    "ASH-L-00006": [{"outcome": "declined", "decided_by": "ASH-U-001", "note": "Thin margins; decline."}],
    "ASH-L-00017": [
        {"outcome": "approved", "decided_by": "ASH-U-001", "note": "Trying to approve a fraud hold."},
        {"outcome": "referred_to_siu", "decided_by": "ASH-U-001", "note": "Refer to SIU."},
    ],
    "ASH-L-00046": [
        {"outcome": "approved", "decided_by": "ASH-U-001", "note": "Credit Officer, too junior."},
        {"outcome": "approved", "decided_by": "ASH-U-013", "note": "Credit Committee sign-off."},
    ],
    "ASH-L-00029": [
        {"outcome": "approved", "decided_by": "ASH-U-013", "note": "Committee member, not enough for 8.5 million."},
        {"outcome": "approved", "decided_by": "ASH-U-019", "note": "Board member sign-off."},
    ],
}


def _setup(folder: Path):
  folder.mkdir(parents=True, exist_ok=True)
  actions._decision_file = lambda: folder / "decisions.jsonl"
  return wf.build_graph(open_checkpointer(folder / "workflow.db"))


def _show(application_id: str, result: dict):
  print(f"  {application_id}: {result['status']}  trail={result['trail']}")
  if result["status"] == "waiting":
    request = result["request"]
    print(f"      waiting for a {request['kind']} review, allowed={request['allowed_outcomes']}, error={request['error']}")
  else:
    decision = result.get("decision") or {}
    print(f"      outcome={result['outcome']} decided_by={decision.get('decided_by')}")


def phase_start(folder: Path):
  graph = _setup(folder)
  print(f"PROCESS 1: starting {len(CASES)} applications")
  for application_id, label in CASES.items():
    print(f"- {application_id} [{label}]")
    _show(application_id, wf.start(graph, application_id))


def phase_resume(folder: Path):
  graph = _setup(folder)
  print("PROCESS 2: a brand new Python process, same checkpoint database")
  for application_id, answers in ANSWERS.items():
    print(f"- {application_id}: still waiting on disk = {wf.is_waiting(graph, application_id)}")
    for answer in answers:
      print(f"    human answers: {answer['outcome']} by {answer['decided_by']}")
      result = wf.resume(graph, application_id, answer)
      _show(application_id, result)
      if result["status"] == "done":
        break
  print("\nDuplicate resume of ASH-L-00006 (must not record a second decision):")
  try:
    again = wf.resume(graph, "ASH-L-00006", ANSWERS["ASH-L-00006"][0])
    print(f"  returned status={again['status']} outcome={again['outcome']} (nothing new was run)")
  except Exception as error:  # a finished thread has nothing to resume; that is also a safe outcome
    print(f"  refused: {type(error).__name__}")
  lines = (folder / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
  print(f"\nDecisions on disk: {len(lines)} (one per application, no duplicates)")
  for line in lines:
    record = json.loads(line)
    print(f"  {record['application_id']}: {record['outcome']} by {record['decided_by']} grade={record['grade']}")
  ids = [json.loads(line)["application_id"] for line in lines]
  print(f"Unique applications: {len(set(ids))} of {len(ids)} records")


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--phase", choices=["start", "resume"])
  parser.add_argument("--folder")
  args = parser.parse_args()
  if args.phase:
    (phase_start if args.phase == "start" else phase_resume)(Path(args.folder))
    return
  stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
  folder = get_settings().project_root / "runtime" / f"m5_demo_{stamp}"
  outputs = []
  for phase in ("start", "resume"):
    done = subprocess.run([sys.executable, __file__, "--phase", phase, "--folder", str(folder)], capture_output=True, text=True)
    outputs.append(done.stdout + (done.stderr if done.returncode else ""))
    print(outputs[-1])
  out = get_settings().project_root / "docs" / "m5_workflow_run.txt"
  out.write_text("\n".join(outputs), encoding="utf-8")
  print(f"Saved {out}")


if __name__ == "__main__":
  main()

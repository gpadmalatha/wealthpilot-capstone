"""Run the M2 agent on three tasks and save the evidence to docs/m2_run_output.txt."""
import logging
import time

from capstone.agents.underwriting_agent import run_agent
from capstone.settings import get_settings

TASKS = [
    "Review application ASH-L-00000: bureau record, DSCR against policy, and whether it can proceed.",
    "Review application ASH-L-00001. It is a large loan: check who must approve it and escalate if needed.",
    "Review application ASH-L-99999 and tell me whether it can proceed.",
]


def main() -> None:
  logging.basicConfig(level=logging.WARNING)
  settings = get_settings()
  lines = [f"model: {settings.llm_model}", f"max_agent_steps: {settings.max_agent_steps}", ""]
  for task in TASKS:
    run = run_agent(task)
    lines.append(f"TASK: {task}")
    for record in run.tool_calls:
      status = "ok" if record.result.ok else f"ERROR {record.result.error.code}"
      lines.append(f"  tool {record.name}({record.arguments}) -> {status}")
    lines.append(f"  stop_reason: {run.stop_reason} after {run.model_calls} model calls")
    lines.append(f"  answer: {run.answer}")
    lines.append("")
    time.sleep(settings.eval_delay_seconds)
  report = settings.project_root / "docs" / "m2_run_output.txt"
  report.write_text("\n".join(lines), encoding="utf-8")
  print("\n".join(lines))


if __name__ == "__main__":
  main()

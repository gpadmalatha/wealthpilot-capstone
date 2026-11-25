"""M7 evidence run: trace one request end to end, then inject bureau failures. Writes docs/m7_reliability_run.txt
and docs/m7_trace_sample.jsonl.

Run:  python scripts\run_m7_reliability.py     (no model calls; takes about 15 seconds because backoff really waits)
"""
import io
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from capstone.mcp.client import call_tools_sync
from capstone.observability import tracing
from capstone.observability.logging import configure_logging
from capstone.reliability.circuit_breaker import CircuitBreaker
from capstone.reliability.fallbacks import BureauSource, ResilientBureau
from capstone.reliability.retries import SourceUnavailableError
from capstone.settings import get_settings
from capstone.tools import actions
from capstone.tools.lookups import get_bureau_report
from capstone.workflows import graph as wf
from capstone.workflows.checkpoints import open_checkpointer

OUT = io.StringIO()


def say(text=""):
  print(text)
  OUT.write(text + "\n")


class FaultyBureau:
  """Fault injection: fails `failures` times with a timeout, then answers like the real bureau."""
  def __init__(self, failures):
    self.failures, self.calls = failures, 0

  def __call__(self, applicant_id):
    self.calls += 1
    if self.calls <= self.failures:
      raise SourceUnavailableError("bureau timed out")
    return get_bureau_report(applicant_id)


def mcp_bureau(applicant_id):
  [result] = call_tools_sync([("get_bureau_report", {"applicant_id": applicant_id})])
  if not result.ok:
    raise SourceUnavailableError(result.error.message)
  return result.data


def run(folder: Path, name: str, application_id: str, chain: ResilientBureau):
  scenario = folder / name
  scenario.mkdir(parents=True, exist_ok=True)
  actions._decision_file = lambda: scenario / "decisions.jsonl"
  actions._handoff_file = lambda: scenario / "handoffs.jsonl"
  graph = wf.build_graph(open_checkpointer(scenario / "workflow.db"), bureau=chain)
  result = wf.start(graph, application_id)
  say(f"  status={result['status']} outcome={result.get('outcome')} bureau_source={result.get('bureau_source') or result.get('request', {}).get('bureau_source')}")
  if result["status"] == "waiting":
    say(f"  paused for human review kind={result['request']['kind']}")
  say(f"  trail={result['trail']}")
  return result


def print_tree(events):
  children = {}
  for event in events:
    children.setdefault(event["parent_id"], []).append(event)

  def walk(parent, depth):
    for event in sorted(children.get(parent, []), key=lambda e: e["started_at"]):
      extra = {k: v for k, v in event["attrs"].items() if k in ("result", "ok", "error_code", "model", "applicant_id")}
      say(f"  {'  ' * depth}{event['name']} [{event['kind']}] {event['status']} {event['duration_ms']}ms {extra or ''}")
      walk(event["span_id"], depth + 1)
  walk(None, 0)


def main():
  configure_logging(logging.WARNING)
  folder = get_settings().project_root / "runtime" / f"m7_demo_{datetime.now():%Y%m%d_%H%M%S}"
  cache = folder / "bureau_cache.json"
  folder.mkdir(parents=True)

  def chain(*sources):
    return ResilientBureau(list(sources), cache_path=cache)

  say("SCENARIO A: bureau times out twice, then answers (bounded retries with backoff). Whole request traced.")
  captured = []
  tracing.set_sink(captured.append)
  primary = FaultyBureau(failures=2)
  run(folder, "a", "ASH-L-00005", chain(BureauSource("bureau_primary", primary, CircuitBreaker("a"))))
  say(f"  primary bureau was called {primary.calls} times for one request")
  say("  trace tree (one trace id for the entire request):")
  print_tree([e for e in captured])
  say(f"  trace_ids in this request: {len({e['trace_id'] for e in captured})}")
  sample = Path(get_settings().project_root / "docs" / "m7_trace_sample.jsonl")
  sample.write_text("\n".join(json.dumps(e) for e in captured) + "\n", encoding="utf-8")
  tracing.set_sink(lambda event: None)

  say("\nSCENARIO B: primary bureau is down, the backup source (the MCP bureau server) answers.")
  run(folder, "b", "ASH-L-00035", chain(BureauSource("bureau_primary", FaultyBureau(99), CircuitBreaker("b1")), BureauSource("bureau_backup_mcp", mcp_bureau, CircuitBreaker("b2"))))

  say("\nSCENARIO C: every live source is down but a recent report is cached: a clean small loan is NOT auto-approved.")
  run(folder, "c", "ASH-L-00005", chain(BureauSource("bureau_primary", FaultyBureau(99), CircuitBreaker("c"))))

  say("\nSCENARIO D: every source is down and nothing is cached: no decision, the file is queued for a human.")
  run(folder, "d", "ASH-L-00022", chain(BureauSource("bureau_primary", FaultyBureau(99), CircuitBreaker("d"))))
  handoffs = (folder / "d" / "handoffs.jsonl").read_text(encoding="utf-8").splitlines()
  say(f"  hand-off records written: {len(handoffs)}; decisions written: {'none' if not (folder / 'd' / 'decisions.jsonl').exists() else 'SOME'}")

  say("\nSCENARIO E: circuit breaker. Threshold 2 failed fetches, cool-down 2 seconds.")
  flaky = FaultyBureau(failures=6)
  breaker = CircuitBreaker("bureau_primary", failure_threshold=2, reset_seconds=2.0)
  e_chain = ResilientBureau([BureauSource("bureau_primary", flaky, breaker)], cache_path=folder / "e_cache.json")
  for number in (1, 2, 3):
    before = flaky.calls
    outcome = e_chain.fetch("ASH-A-00005")
    say(f"  fetch {number}: status={outcome.status} breaker={breaker.state} calls_to_bureau={flaky.calls - before} note={outcome.attempts[0]}")
  say("  waiting 2.1 seconds for the cool-down, and the bureau recovers ...")
  flaky.failures = 0
  time.sleep(2.1)
  say(f"  breaker after cool-down: {breaker.state}")
  outcome = e_chain.fetch("ASH-A-00005")
  say(f"  fetch 4 (one trial call): status={outcome.status} breaker={breaker.state}")

  path = get_settings().project_root / "docs" / "m7_reliability_run.txt"
  path.write_text(OUT.getvalue(), encoding="utf-8")
  say(f"\nSaved {path} and {sample}")


if __name__ == "__main__":
  main()

"""Run-level KPIs from trace spans: tokens, cost and latency per run and per step, plus error and fallback rates.

Reads the JSON-lines spans that tracing.py writes (runtime/traces/*.jsonl) and returns plain numbers. The same code is
used by scripts/trace_kpis.py (a printable table) and by the tests. Standard library only.
"""
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Optional


def load_events(paths: Iterable[Path]) -> list[dict]:
  events: list[dict] = []
  for path in paths:
    for line in Path(path).read_text(encoding="utf-8").splitlines():
      if line.strip():
        events.append(json.loads(line))
  return events


def percentile(values: list[float], fraction: float) -> float:
  """Nearest-rank percentile (fraction 0.95 = p95). 0.0 for an empty list."""
  if not values:
    return 0.0
  ordered = sorted(values)
  rank = max(1, -(-int(fraction * 1000) * len(ordered) // 1000))  # ceil without floating point error
  return ordered[min(rank, len(ordered)) - 1]


def _is_degraded(event: dict) -> bool:
  attrs = event.get("attrs") or {}
  return bool(attrs.get("used_fallback")) or attrs.get("result") in ("failed", "circuit_open")


def summarise(events: list[dict]) -> dict:
  """Group spans into runs (one per trace) and steps (one per span name) and total everything."""
  runs: dict[str, dict] = {}
  steps: dict[tuple[str, str], dict] = defaultdict(lambda: {"calls": 0, "errors": 0, "durations": [], "tokens": 0, "cost_usd": 0.0})
  for event in events:
    attrs = event.get("attrs") or {}
    run = runs.setdefault(event["trace_id"], {"trace_id": event["trace_id"], "name": None, "session_id": None, "user_id": None,
                                              "duration_ms": 0.0, "spans": 0, "llm_calls": 0, "tokens": 0, "cost_usd": 0.0,
                                              "errors": 0, "degraded": 0, "retries": 0})
    run["spans"] += 1
    run["session_id"] = run["session_id"] or event.get("session_id")
    run["user_id"] = run["user_id"] or event.get("user_id")
    if event.get("kind") == "request":
      run["name"], run["duration_ms"] = event["name"], event.get("duration_ms", 0.0)
    if event.get("status") == "error":
      run["errors"] += 1
    if _is_degraded(event):
      run["degraded"] += 1
    run["retries"] += int(attrs.get("retries") or 0)
    tokens = int(attrs.get("prompt_tokens") or 0) + int(attrs.get("completion_tokens") or 0)
    cost = float(attrs.get("cost_usd") or 0.0)
    if event.get("kind") == "llm":
      run["llm_calls"] += 1
      run["tokens"] += tokens
      run["cost_usd"] += cost
    step = steps[(event.get("kind", "step"), event["name"])]
    step["calls"] += 1
    step["errors"] += 1 if event.get("status") == "error" else 0
    step["durations"].append(event.get("duration_ms", 0.0))
    step["tokens"] += tokens if event.get("kind") == "llm" else 0
    step["cost_usd"] += cost if event.get("kind") == "llm" else 0.0
  dependency_spans = [e for e in events if e.get("kind") == "dependency"]
  total_spans = len(events)
  run_list = sorted(runs.values(), key=lambda r: r["trace_id"])
  return {
      "runs": run_list,
      "steps": {key: {"calls": v["calls"], "errors": v["errors"], "p50_ms": percentile(v["durations"], 0.5),
                      "p95_ms": percentile(v["durations"], 0.95), "tokens": v["tokens"], "cost_usd": round(v["cost_usd"], 8)}
                for key, v in sorted(steps.items())},
      "totals": {
          "runs": len(run_list), "spans": total_spans,
          "llm_calls": sum(r["llm_calls"] for r in run_list), "tokens": sum(r["tokens"] for r in run_list),
          "cost_usd": round(sum(r["cost_usd"] for r in run_list), 8),
          "run_p50_ms": percentile([r["duration_ms"] for r in run_list], 0.5),
          "run_p95_ms": percentile([r["duration_ms"] for r in run_list], 0.95),
          "error_rate": round(sum(1 for e in events if e.get("status") == "error") / total_spans, 4) if total_spans else 0.0,
          "fallback_rate": round(sum(1 for e in dependency_spans if _is_degraded(e)) / len(dependency_spans), 4) if dependency_spans else 0.0,
      },
  }


def format_report(summary: dict, title: Optional[str] = None) -> str:
  lines = [title or "KPIs from request traces", ""]
  totals = summary["totals"]
  lines += [f"runs: {totals['runs']}   spans: {totals['spans']}   model calls: {totals['llm_calls']}",
            f"tokens: {totals['tokens']}   cost: ${totals['cost_usd']:.6f}",
            f"run latency p50: {totals['run_p50_ms']:.0f} ms   p95: {totals['run_p95_ms']:.0f} ms",
            f"error rate (spans): {totals['error_rate']:.1%}   fallback/degraded rate (dependency calls): {totals['fallback_rate']:.1%}", "",
            "Per run:",
            f"  {'trace':34s} {'request':18s} {'ms':>9s} {'spans':>6s} {'llm':>4s} {'tokens':>8s} {'cost $':>10s} {'err':>4s} {'degr':>5s} {'retry':>6s}  session / user"]
  for run in summary["runs"]:
    lines.append(f"  {run['trace_id'][:34]:34s} {str(run['name'])[:18]:18s} {run['duration_ms']:9.0f} {run['spans']:6d} {run['llm_calls']:4d} "
                 f"{run['tokens']:8d} {run['cost_usd']:10.6f} {run['errors']:4d} {run['degraded']:5d} {run['retries']:6d}  {run['session_id']} / {run['user_id']}")
  lines += ["", "Per step (kind, name):",
            f"  {'kind':11s} {'name':32s} {'calls':>6s} {'err':>4s} {'p50 ms':>9s} {'p95 ms':>9s} {'tokens':>8s} {'cost $':>10s}"]
  for (kind, name), step in summary["steps"].items():
    lines.append(f"  {kind:11s} {name[:32]:32s} {step['calls']:6d} {step['errors']:4d} {step['p50_ms']:9.1f} {step['p95_ms']:9.1f} "
                 f"{step['tokens']:8d} {step['cost_usd']:10.6f}")
  return "\n".join(lines) + "\n"

"""M7 failure injection: a seeded fault harness measures the bureau pull BEFORE and AFTER hardening.

Before = one plain call to the primary bureau (no retries, no breaker, no backup, no cache).
After  = the real ResilientBureau: bounded retries with backoff, circuit breaker, backup source, last-good cache.

Three seeded fault scenarios, 300 requests each over 60 applicants:
  1. random transient timeouts on both sources (30 percent of calls),
  2. the primary bureau is down for requests 100-199 (the backup answers),
  3. both bureaus are down for requests 100-199 (only the cache or a human queue can answer).

"Usable answer" = a live or cached bureau report. An unavailable request is queued for a human (never decided automatically).
No model calls and no real waiting: backoff sleeps are added to a simulated clock.

Run:  python scripts\\run_failure_injection.py        Writes docs/m7_failure_injection.txt
"""
import io
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capstone.observability.kpis import percentile  # noqa: E402
from capstone.reliability.circuit_breaker import CircuitBreaker  # noqa: E402
from capstone.reliability.fallbacks import CACHE, LIVE, BureauSource, ResilientBureau  # noqa: E402
from capstone.reliability.retries import SourceUnavailableError  # noqa: E402
from capstone.settings import get_settings  # noqa: E402
from capstone.tools.lookups import get_bureau_report  # noqa: E402

SEED = 42
REQUESTS = 300
APPLICANTS = [f"ASH-A-{number:05d}" for number in range(60)]
OUTAGE = range(100, 200)  # request numbers during which a source is hard down
TRANSIENT_RATE = 0.30
SECONDS_PER_REQUEST = 1.0  # simulated time between requests (the breaker cool-down runs on this clock)
BREAKER_RESET_SECONDS = 20.0

OUT = io.StringIO()


def say(text=""):
  print(text)
  OUT.write(text + "\n")


class Clock:
  def __init__(self):
    self.now = 0.0

  def __call__(self):
    return self.now

  def sleep(self, seconds):
    self.now += seconds


class Source:
  """A bureau that fails by the scenario's rules, otherwise answers like the real mock bureau."""
  def __init__(self, rng, current_request, transient_rate=0.0, down_during=None):
    self.rng, self.current_request = rng, current_request
    self.transient_rate, self.down_during = transient_rate, down_during
    self.calls = 0

  def __call__(self, applicant_id):
    self.calls += 1
    if self.down_during is not None and self.current_request() in self.down_during:
      raise SourceUnavailableError("bureau is down")
    if self.rng.random() < self.transient_rate:
      raise SourceUnavailableError("bureau timed out")
    return get_bureau_report(applicant_id)


def run_scenario(name, primary_args, backup_args):
  """Return metrics for the same request stream through the unhardened path and the hardened path."""
  results = {}
  for label in ("before", "after"):
    rng, clock, request_number = random.Random(SEED), Clock(), {"n": 0}
    pick = random.Random(SEED + 1)  # which applicant each request is about: identical for both runs
    current = lambda: request_number["n"]  # noqa: E731
    primary = Source(random.Random(SEED + 2), current, **primary_args)
    backup = Source(random.Random(SEED + 3), current, **backup_args)
    usable = live = cached = queued = 0
    latencies = []
    if label == "after":
      breaker = CircuitBreaker("bureau_primary", failure_threshold=get_settings().breaker_failure_threshold,
                               reset_seconds=BREAKER_RESET_SECONDS, clock=clock)
      with tempfile.TemporaryDirectory() as folder:
        chain = ResilientBureau([BureauSource("bureau_primary", primary, breaker), BureauSource("bureau_backup", backup)],
                                cache_path=Path(folder) / "cache.json", sleep=clock.sleep)
        random.seed(SEED)  # retry jitter
        for number in range(REQUESTS):
          request_number["n"] = number
          started = clock.now
          outcome = chain.fetch(pick.choice(APPLICANTS))
          latencies.append(clock.now - started)
          clock.now += SECONDS_PER_REQUEST
          live += outcome.status == LIVE
          cached += outcome.status == CACHE
          queued += outcome.status not in (LIVE, CACHE)
          usable += outcome.status in (LIVE, CACHE)
    else:
      for number in range(REQUESTS):
        request_number["n"] = number
        applicant = pick.choice(APPLICANTS)
        try:
          primary(applicant)
          live += 1
          usable += 1
        except SourceUnavailableError:
          queued += 1
        latencies.append(0.0)
    results[label] = {"usable": usable, "live": live, "cached": cached, "queued_for_human": queued,
                      "primary_calls": primary.calls, "p95_wait_s": percentile(latencies, 0.95)}
  say(f"SCENARIO {name}")
  say(f"  {'':24s} {'usable answers':>16s} {'live':>6s} {'cache':>6s} {'to human':>9s} {'primary calls':>14s} {'p95 backoff wait':>17s}")
  for label in ("before", "after"):
    r = results[label]
    say(f"  {label + ' hardening':24s} {r['usable']:>7d}/{REQUESTS} = {r['usable'] / REQUESTS:>4.0%} {r['live']:>6d} {r['cached']:>6d} "
        f"{r['queued_for_human']:>9d} {r['primary_calls']:>14d} {r['p95_wait_s']:>15.1f} s")
  say()
  return results


def main():
  say(f"Seeded fault injection (seed {SEED}), {REQUESTS} requests per scenario, {len(APPLICANTS)} applicants.")
  say(f"Retries: {get_settings().retry_max_attempts} tries with exponential backoff; breaker opens after "
      f"{get_settings().breaker_failure_threshold} failures, cool-down {BREAKER_RESET_SECONDS:.0f} simulated seconds.\n")
  all_results = {
      "1 random timeouts (30% of calls, both sources)": run_scenario("1: random timeouts, 30 percent of calls on both sources", {"transient_rate": TRANSIENT_RATE}, {"transient_rate": TRANSIENT_RATE}),
      "2 primary down, backup up": run_scenario("2: primary bureau down for requests 100-199, backup healthy", {"down_during": OUTAGE}, {}),
      "3 both down": run_scenario("3: both bureaus down for requests 100-199 (cache or human queue only)", {"down_during": OUTAGE}, {"down_during": OUTAGE}),
  }
  say("Summary (usable-answer rate, before -> after):")
  for name, r in all_results.items():
    say(f"  {name:48s} {r['before']['usable'] / REQUESTS:>5.1%} -> {r['after']['usable'] / REQUESTS:>5.1%}")
  say("\nIn every scenario a request with no usable report is queued for a human; none is decided automatically.")
  (Path(__file__).resolve().parents[1] / "docs" / "m7_failure_injection.txt").write_text(OUT.getvalue(), encoding="utf-8")


if __name__ == "__main__":
  main()

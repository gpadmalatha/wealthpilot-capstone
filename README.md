# WealthPilot: SME Loan Underwriting and Credit Research Assistant

**Applied AI Professional Certification Program · IIT Hyderabad · Capstone PS3**

WealthPilot helps credit analysts at a fictional lender (Ashva Capital) assess
small-business loan applications against the Credit Policy Manual. Code makes
every policy decision; models read documents, answer policy questions and give
advisory opinions. Humans sign off every decision except one narrow, policy-allowed
automatic decline.

## Status

All milestones M1 to M8 are implemented with committed run output.
See `docs/milestone_checklist.md` for the evidence table and
`docs/evaluation_report.md` for results (18 of 20 golden cases pass; 3 of 3 matched
bias pairs identical; two failures explained, not tuned away).

| Document | Purpose |
|---|---|
| `docs/architecture.md` | Request flow, rule-to-enforcement table, components, failure behaviour |
| `docs/data_sources.md` | Dataset versions, seed, counts and checksums |
| `docs/demo_steps.md` | Setup, start the service, sample requests, approval walkthrough |
| `docs/evaluation_report.md` | Evaluation method, results, failed cases, limitations |
| `docs/milestone_checklist.md` | M1 to M8 acceptance evidence and commands |

## Quick start (Windows Command Prompt)

```
python -m venv C:\venvs\wealthpilot
C:\venvs\wealthpilot\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env
```

The synthetic toolkit data is not in the repository (it is git-ignored). Generate it
with the course Data Toolkit (`python generate.py --domain wealthpilot`, toolkit 1.0.4,
seed 42) and copy the output to `data/wealthpilot/`; see `docs/data_sources.md`.
The tests stop with a clear message if it is missing.

Put your own model API key in `.env` (never commit it). Then:

```
python -m pytest tests\unit -q
python scripts\check_policy_engine.py
uvicorn capstone.api.main:get_app --factory
```

Full instructions, including the approval and resume walkthrough, are in
`docs/demo_steps.md`. Docker files are included but were not built in the
development environment.

## Known limitations

Two evaluation cases fail (EV-910 scorer strictness, EV-905 expected route);
the golden set was visible during development; tracing is a local JSON-lines
sink, not LangFuse; Docker is unverified. Details are in the evaluation report.

## Reproduce from a clean clone

```bat
python -m venv C:\venvs\wealthpilot
C:\venvs\wealthpilot\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env          :: then put YOUR key in .env; never commit it
python -m pytest tests -q       :: no key needed; the model is stubbed
```

The synthetic toolkit data is committed in `data/wealthpilot`. The commands below write the evidence files in `docs/`.

| Needs a key? | Command | Evidence |
|---|---|---|
| no | `python scripts\run_failure_injection.py` | `docs/m7_failure_injection.txt` |
| no | `python scripts\run_probes.py` | `docs/m8_probe_results.txt` |
| no | `python scripts\run_m7_reliability.py` then `python scripts\trace_kpis.py` | trace spans and KPIs |
| yes | `python scripts\run_m7_observability.py` | `docs/m7_llm_trace_sample.jsonl`, `docs/m7_kpis.txt` |
| yes | `python scripts\run_final_evaluation.py --judge` | `docs/m8_evaluation_results.txt` (components, own adversarial cases, LLM judge) |
| yes | `python scripts\run_m6_team_resume.py` | `docs/m6_team_resume_run.txt` |
| yes | `python scripts\demo_api.py` | `docs/m8_api_demo.txt` |

Design: `docs/architecture.md`, `docs/m6_team_design.md`. Honest limits: `docs/evaluation_report.md`.

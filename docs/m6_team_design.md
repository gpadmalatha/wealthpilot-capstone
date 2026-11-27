# M6 — The credit committee as a team

**Principle: code decides, models read, humans sign off.** The committee is advisory. It never records a decision.

## Why more than one agent
One model writing and then checking its own memo repeats its own blind spots. Splitting the work gives separation of duties:

| Role | Does | Tools | Sees | May write |
|---|---|---|---|---|
| Evidence Collector | fetches bureau, bank, bureau-policy via MCP tools and reads the `policy://credit-policy/limits` resource | the only role with tools | everything it fetches | `evidence` |
| Analyst (actor) | writes the memo and a recommendation, revises on feedback | none | all evidence | `memo`, `round` |
| Policy Guard | deterministic checks (policy engine result, prohibited terms, citations); no model | none | evidence + memo | `guard_verdict` |
| Risk Reviewer (critic) | credit-risk checklist | none | policy, bureau, bank summary only | `risk_verdict` |
| Compliance Reviewer (critic) | fair-lending and process checklist | none | policy, documents, bureau policy, limits only | `compliance_verdict` |
| Supervisor | pure code: accept, revise, reject, escalate or exhaust | none | verdicts | `feedback`, `verdict_log`, `outcome`, `final_recommendation` |

Mapping to the PS3 roster: Analyst = Credit Analyst; Risk Reviewer = Risk Officer; Compliance Reviewer = Compliance Officer; Policy Guard + Supervisor = the deterministic policy engine and committee chair; the human signatory in the workflow = Credit Committee / Board.

## Control flow
`evidence_collector -> analyst -> policy_guard -> risk_reviewer -> compliance_reviewer -> supervisor`, then a conditional edge: any `escalate` or `reject` ends with outcome refer; all `accept` ends `agreed`; otherwise loop back to the Analyst with the reviewers' issues until `max_committee_rounds` (default 3), then `exhausted` and a human takes over. A LangGraph `recursion_limit` is a second cap. Any model or MCP failure returns `unavailable` with recommendation `refer`.

## Enforced boundaries (tests/unit/test_committee.py)
- `AGENT_TOOLS` / `AGENT_RESOURCES`: a tool or resource outside an agent's list raises `PermissionError`.
- `slice_for`: each reviewer receives only its own slice of evidence.
- `AGENT_WRITES`: a node returning a key outside its list raises `PermissionError`.
- Every model output is validated against a Pydantic schema before use.

## Human review and checkpoint
With `COMMITTEE_ENABLED=true` the API workflow runs the committee before `human_review`. The memo is stored in the SQLite checkpoint, the run pauses at the human interrupt, and `scripts/run_m6_team_resume.py` kills the process and resumes in a new one: one decision, recorded by a human. Output: `docs/m6_team_resume_run.txt`.

## Known limits
The reviewers are the same model with different prompts, so their errors are correlated; the deterministic guard and the human are the real checks. The committee is off by default.

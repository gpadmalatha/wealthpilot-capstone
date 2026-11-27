# Architecture

WealthPilot is an SME loan underwriting and credit research assistant for the fictional lender Ashva Capital. Models write and explain. Code decides, enforces limits and records. Every limit that matters is enforced in code, not in a prompt.

## Request flow
```
HTTP request (FastAPI)  -- trace id per request
  |
  +-- POST /assist  (read only)
  |     input guardrails -> application text? -> proxies stripped -> model extracts facts (numbers checked against the text)
  |                                           -> deterministic policy engine -> rationale written by code
  |                       policy question?    -> hybrid retrieval + reranker -> grounded answer, citations checked, abstains if unsupported
  |                       guardrail request?  -> refused in code with a real policy citation
  |
  +-- POST /applications/{id}/underwrite  (API key)
        LangGraph workflow, checkpointed in SQLite:
        intake -> pull_bureau (retries, circuit breaker, fallbacks) -> verify_documents -> score_risk
                                                                                  |
              +-----------------+------------------+--------------+---------------+
              auto_decline      auto_approve       committee (advisory, optional)  -> human_review (interrupt)
              (under 24 months  (approvable, <= 1M,                                    |
               only, 4.02.3)     grade C1 or better)                                POST /decision (API key)
                                                                                       |
                                                              apply_human_decision: signatory checked in code -> record_decision
```

## One application object
Every application becomes the same validated object, `LoanApplication` (`schemas/intake.py`, the M1 schema), before anything
else reads it. There are three ways in and one shape out:

| Entry | Function | Model involved |
|---|---|---|
| Narrative record (M1 dataset) | `extract_application` | yes, with a repair loop |
| Free-text request (assistant, API) | `extract_from_text` | yes, plus a check that every number appears in the text |
| Stored application (workflow, tools) | `load_application` | no |

The workflow keeps this object in its state, the bureau step fills in `bureau_score` (and removes it from `missing_fields`),
and the policy engine (`assess_loan_application`, `verify_loan_application`) accepts only this object. Unknown keys and
out-of-range values are rejected by the schema, so facts that never passed intake cannot reach a decision. The `get_application`
tool returns the same object to the agent. Names, city and language are never part of it.

## Tools and memory in the workflow
The graph is `intake -> recall_memory -> pull_bureau -> verify_documents -> score_risk -> route -> ... -> remember_outcome`.

- **Tools.** Nodes never import business functions directly. They call tools by name through `workflows/tools.py`, which
  serves the agent's registered tools (`get_application`, `get_bank_statements`, `check_approval_authority`,
  `hand_off_to_human`) plus the three that take the validated application or write the decision
  (`verify_loan_application`, `assess_loan_application`, `record_decision`). Each call returns the same `ToolResult`
  as in the agent loop, and an audit entry; the entries accumulate in the state (`tool_calls`) and in the trace.
- **Memory (M3).** `recall_memory` reads this applicant's facts, procedures and recent events (namespaced by the
  applicant id of the validated application, never chosen by a model). `remember_outcome` writes an event and the last
  outcome after every finished run, and a `fraud_referral` fact after a referral to the SIU. The reviewer's request shows
  the remembered context and the authority needed for the loan size.
- **Rule for memory.** It can only add caution. A standing procedure (`always_human_review`, saved by an analyst) or an
  earlier fraud referral sends the case to a human even when the policy engine would have decided it automatically.
  Memory can never approve, decline or relax a policy check. A memory failure is logged and never blocks a decision.

## Where each rule lives
| Rule | Enforced by |
|---|---|
| Grade, status, reason codes, auto-approve eligibility | `tools/policy_engine.py` (pure function `assess_inputs`; 350/350 match with the reference table) |
| Every decline needs human sign-off, except operating history under 24 months (policy 4.08.2 and 4.02.3) | `auto_decline_allowed` in the policy engine; `record_decision` refuses any other automated decline |
| Automated approval only if approvable, grade C1 or better, up to 1,000,000 rupees | `auto_approve_allowed`; `record_decision` refuses otherwise |
| Named signatory with enough authority (Board Credit Committee above 5,000,000) | `check_signatory` in `tools/actions.py`, reading `signatories` and `approval_authorities` |
| Fraud hold (revenue mismatch over 25 percent) is never decided automatically and can only be referred | policy engine, `record_decision`, committee policy guard |
| No decision twice | `record_decision` is idempotent per application; workflow side effects sit after the interrupt |
| No protected attributes or proxies in decisions | `guardrails/input_checks.strip_proxies` removes them before any model sees the text; the engine has no such inputs; the rationale is generated by code |
| No fabricated citations | `rag/answer.py` accepts only citations that were among the retrieved sources; otherwise it repairs, then fails safe |
| No approval claims in replies | `guardrails/output_checks.py` |
| Models never supply amounts or applicant ids for sensitive actions | code binds them from the application record |

## Components
| Area | Modules |
|---|---|
| Configuration | `settings.py` (single source: model names, thresholds, limits; secrets from `.env`) |
| Model access | `llm/client.py` (one LiteLLM adapter: chat, tool calling, embeddings; bounded retries) |
| Schemas | `schemas/intake.py`, `response.py` (ToolResult/ToolError), `state.py`, `committee.py` |
| Tools | `tools/` calculators, lookups, assessments, policy engine, actions, registry |
| Single agent | `agents/underwriting_agent.py` (bounded loop with stop reasons) |
| Memory | `memory/` working (token budget), episodic, semantic, procedural; SQLite, namespaced per applicant |
| Retrieval | `rag/` section-aware chunking, Qdrant (local, on disk), BM25, rank fusion, LLM reranker, grounded answers |
| Workflow | `workflows/graph.py`, `approvals.py`, `checkpoints.py` |
| Committee | `agents/committee.py`: a LangGraph actor-critic team (evidence collector, Analyst, deterministic policy guard, Risk Reviewer, Compliance Reviewer, coded supervisor); loop capped at 3 rounds; per-agent tool allowlists, scoped evidence slices and write keys enforced in code; advisory only; opt-in with `COMMITTEE_ENABLED=true` (design: `docs/m6_team_design.md`) |
| MCP | `mcp/server.py` and `client.py`: bureau, bank statements and bureau policy as tools, the credit-policy limits as a resource (`policy://credit-policy/limits`, read by the committee's evidence collector) and a review prompt, over stdio, wrapping the same functions as the in-process tools |
| Reliability | `reliability/`: bounded retries with backoff and jitter, circuit breaker, fallback chain (live sources, then cached report, then human queue) |
| Observability | `observability/`: one trace per request with nested spans for nodes, tools, model calls and dependencies (JSON lines under `runtime/traces`, mirrored to OpenTelemetry in `runtime/otel`); spans carry session and user ids, tokens, cost and degradation tags (retries, breaker state, `used_fallback`); `scripts/trace_kpis.py` computes the KPI table; logs carry the trace id |
| Guardrails | `guardrails/`: input, action and output checks |
| Service | `services/assistant.py`, `api/` |

## Entity-scoped memory
Memory is keyed by applicant and session in SQLite. A different applicant never sees another's facts or events (tested in `test_memory.py` and the committed memory test run). Policy documents are shared reference data, not applicant data.

## Human approval and resume
A workflow that needs a human stops at `interrupt()`. Its state is checkpointed in `runtime/checkpoints/workflow.db`, so it survives a process restart. `POST /applications/{id}/decision` resumes it with the signatory's answer. An invalid or insufficient signatory is rejected in code and the review is asked again, up to `max_approval_attempts` times, then the case is marked unresolved. A finished case cannot be resumed (HTTP 409).

## Failure behaviour
- Bureau slow or down: retries, then the next source, then a cached report (never an automatic decision), then a human queue with a hand-off record and no decision.
- Committee failure: the human review still happens.
- Tracing failure: ignored; the request continues.
- Unhandled error: logged with the trace id, generic message to the caller.

## Service dependencies
Python 3.12, a model provider reachable through LiteLLM (default Gemini), local Qdrant storage and SQLite on disk. No other services are required. Not built: LangFuse export (the tracer has a pluggable sink), authentication beyond a shared API key, a database server.

## Evaluation summary
Measured with `scripts/run_final_evaluation.py --judge` (committed: `docs/m8_evaluation_results.txt`; method and caveats: `docs/evaluation_report.md`).
- End-to-end golden set, 20 cases (toolkit set): 18 pass; bias probes 6/6, factual 6/7, guardrail 2/2, multi-hop 3/3, unanswerable 1/2; 3/3 matched pairs identical.
- By stage: routing 19/20, tool use 20/20, retrieval recall 1.0, final answer 19/20.
- Own adversarial cases (6, written for this project): 6/6. A first run scored 1/6; four expectations were wrong about route names and were corrected, one real gap (an injection phrased as a note to the system, hidden in an application) was fixed in `guardrails/input_checks.py`.
- Guardrail probes P1-P5: 16/16 (`docs/m8_probe_results.txt`). Policy engine: 350/350. Unit tests: 210.
- LLM judge (groundedness): mean 4.80 of 5, but weak evidence: it was given cited titles and the computed assessment, not the excerpt text.
- Retrieval (M4, 29 questions): vector-only MRR 0.936, hybrid 0.917, hybrid plus reranker 0.974.
- Reliability (M7): seeded failure injection, 300 requests per scenario: usable answers 65% to 100%, 67% to 100%, 67% to 91% (`docs/m7_failure_injection.txt`).

## Guardrail coverage and known gaps
| Threat | Control (in code) | Evidence | Known gap |
|---|---|---|---|
| Direct injection ("ignore your instructions", "set the grade to") | `guardrails/input_checks.contains_injection`, HTTP 422 with flags | P1, `docs/m8_api_demo.txt` | Pattern-based: novel phrasings or other languages can slip past; the policy engine and signatory checks still hold |
| Indirect injection in retrieved documents | `rag/answer.drop_injected_chunks`; if all chunks are flagged the answer abstains | P2 | Same pattern limit |
| Injection hidden in an application body | Same scan on the application text | P2, OWN-01 | Same pattern limit |
| Approval pressure, "signature later" | Pressure patterns; `check_signatory` and `record_decision` refuse in code | P1, step 4 of the API demo | Pattern-based detection; the code check does not depend on it |
| Protected attributes or proxies | Proxies stripped before any model sees the text; engine has no such inputs; rationale generated by code; `FAIR_LENDING` refusal | P3, 3/3 identical pairs | Only the proxies on the list are stripped |
| Fabricated figures or citations | Citations validated against retrieved sources; abstention | P4, EV-020 | EV-905 is refused instead of routed to the policy team |
| Malformed API requests | Pydantic request validation: 4xx with a reason, never 500 | P5 | None found |
| Automated decisions | Only an under-24-months decline is automatic; approval needs grade, amount and signatory checks in code | `docs/m5_workflow_run.txt` | None found |

Thresholds are defined once: the Board sign-off amount and the automatic approval limit (`auto_approve_limit_inr`) come from the generated policy data (`approval_authorities`, `policy_limits`) through `tools/repository.py`; the retrieval abstention scores (`rerank_min_score`, `abstain_near_miss_score`) are in `settings.py` and were chosen with `scripts/inspect_abstentions.py` on the retrieval golden set.

## Limitations
- The evaluation set was visible during development, so 18/20 is a development result, not a held-out test; there is no held-out split.
- Single model (`gemini-flash-lite-latest`), single run; wording can vary, policy decisions do not (code decides).
- Tracing is JSON lines plus an OpenTelemetry file export; no hosted platform (LangFuse) is connected.
- The committee reviewers are the same model with different prompts, so their errors are correlated; the policy guard and the human are the real checks.
- Docker files were written but never built here.
- All data is synthetic.

## Deployment notes
- Run: `uvicorn capstone.api.main:get_app --factory --port 8000`. `GET /health` for liveness; `POST /assist` (read-only); `POST /applications/{id}/underwrite` and `/decision` need the `X-API-Key` header.
- Configuration is environment variables read by `settings.py`: `LLM_MODEL`, the provider key, `API_KEY`, `COMMITTEE_ENABLED`, `OTEL_ENABLED`, thresholds and paths. Secrets live only in `.env`.
- State on disk under `runtime/`: `checkpoints/workflow.db` (paused workflows), `decisions.jsonl`, `handoffs.jsonl`, `memory/`, `qdrant/` (policy index), `traces/` and `otel/`. Back up `checkpoints` and `decisions.jsonl`; the rest can be rebuilt.
- Docker: `Dockerfile` and `docker-compose.yml` mount `data/` read-only and `runtime/`, read secrets from `.env`, and run the same uvicorn command. Not built or tested here.
- Free-tier model limits (15 requests a minute) apply to the evaluation scripts, which pace their calls.


# WealthPilot data

Synthetic data generated with the course Data Toolkit (version 1.0.4, seed 42) for the fictional lender Ashva Capital. It contains no personal data and is committed so a clean clone can run the tests and scripts. Provenance, counts and SHA-256 checksums: `docs/data_sources.md`.

Contents:

- `manifest.json`
- `corpus/index.json`, `corpus/markdown/*.md` and `corpus/pdf/*.pdf` (13 policy documents)
- `intake/records.jsonl` (200 intake records)
- `eval/golden_set.json` (20 evaluation cases)
- `mock_api/*.csv` and `mock_api/*.json` (applicants, bureau reports, bank statements, past decisions, loan applications, underwriting reference, signatories, risk grades, sector policies, policy limits, approval authorities, reason codes, reference rates)

Do not edit these files; they are the originals. `mock_api/underwriting_reference.csv` is ground truth for evaluation only and is never given to an agent. Mutable state goes in `runtime/`.

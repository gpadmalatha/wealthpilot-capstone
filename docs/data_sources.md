# Data sources

All data is synthetic, generated with the course Data Toolkit. No real personal data is used, and no external dataset is downloaded or bundled.

## Generation
| Item | Value |
|---|---|
| Toolkit version | 1.0.4 |
| Command | `python generate.py --domain wealthpilot` (run in the toolkit folder) |
| Seed | 42 |
| Generated at | 2026-11-19T12:11:55Z |
| Text generator | Gemini, `gemini-flash-lite-latest` |
| Domain | WealthPilot, SME loan underwriting and credit research (fictional lender Ashva Capital) |

The generated data lives in `data/wealthpilot/` and is git-ignored. Only `data/README.md` files are tracked. To reproduce, run the toolkit with the command above and copy its `wealthpilot` output folder to `data/wealthpilot/`.

## Observed output (from manifest.json)
| Asset | Count |
|---|---|
| Policy corpus documents | 13 (111 chunks after our chunking) |
| Intake records | 200 |
| Mock API tables | applicants 350, bureau_reports 350, bank_statements 1,200, past_decisions 220, loan_applications 350, underwriting_reference 350, signatories 20, risk_grades 8, sector_policies 8, policy_limits 11, approval_authorities 3, reason_codes 15, reference_rates 7 |
| Golden evaluation set | 20 cases: bias_probe 6, factual 7, multi_hop 3, guardrail 2, unanswerable 2 |

`underwriting_reference` is ground truth for evaluation only. It is never given to an agent. `scripts/check_policy_engine.py` compares it with the policy engine (350/350 match on grade, status, reason codes and auto-approve).

## Checksums (SHA-256)
| File | SHA-256 |
|---|---|
| manifest.json | e6622c2e9d75a581e9ccde2fcfdfe2396a49cd21eb3a7cfb3eaec976ad859bb6 |
| corpus/index.json | ada19dfd496751c0e9ba3f4adb4f083945c204c1731475a3a90fa5938e8f8222 |
| intake/records.jsonl | a5c9ebd09f51e674be18bc9062e8b8301e0de0c6bc305373efa8df11c88a8bbf |
| eval/golden_set.json | c05bf177d6bb969a961397530e927ca6159d4659c2485825ad441f54aa2bd927 |
| mock_api/applicants.csv | 0b89fe9a31b41354d0eed2b1aad2f878a067afe64057b4c3af6de60d6e4e43a5 |
| mock_api/approval_authorities.csv | 105b55af1deac76e0164c4999b04418c28f034aa30725f7a66ad8f6f5bb33946 |
| mock_api/bank_statements.csv | 1d432fe3418a03556ee508cfa9226d747147fcb575100592c1e9ac2bd8b75381 |
| mock_api/bureau_reports.csv | 2ec2db6175b726cc312a2469e457c2dc39a684100aadd3ac7f98b0d106fbf9f4 |
| mock_api/loan_applications.csv | ac63d8b8639911bc06c8283ab20f64b20a139194b205f598a580973c4f996f96 |
| mock_api/past_decisions.csv | 3279b50bd4468fa18c5e94724676d6c7471757d03c89e8aac904764ee4e7f040 |
| mock_api/policy_limits.csv | b3b0f9dd242f57ae57f955a64821cf0b96c363c42232d9bebe4465b0f6c1f879 |
| mock_api/reason_codes.csv | dfa0d21227e0238a06bc5c432d512b83581c081a87c04c36a2c4a066b37eb4ab |
| mock_api/reference_rates.csv | 5b68f1a640d47f58806d3ee178fe92947568f18b467caf21de878111f47052ad |
| mock_api/risk_grades.csv | fe8fe136dd52e70ac0860a103d94010079b3e72d56036e5a95db2bad09d5e1a5 |
| mock_api/sector_policies.csv | a75ac47389b4850857db9f5e39ff486e989c760a5b7e24fa60c7f33776ce233c |
| mock_api/signatories.csv | b5a22af2bca26fdc68349e7910447b345d750872248dd85ff4fa3c9260d97356 |
| mock_api/underwriting_reference.csv | e5caeac6ba209ba52127950ef811e0bc7871dcb385496bcbbba30e1321dea34a |

`evaluation/datasets/final_golden.json` is a committed copy of `eval/golden_set.json`, so the final evaluation is reproducible from the repository alone. The retrieval golden set (`evaluation/datasets/retrieval_golden.json`, 29 questions) was written by us from the generated corpus.

## Public sources referenced by the toolkit (not downloaded)
The toolkit manifest lists these as inspiration for the synthetic data. None is used directly in this project.
- SBA 7(a) and 504 Loan Data Reports (US Government work, public domain)
- RBI Master Direction on MSME lending (Government of India publication)
- Home Credit Default Risk (Kaggle, non-commercial terms)
- Lending Club loan data (consumer lending; structure only, not used)
- CFPB Consumer Complaint Database

## Licences and attribution
No external data is included in the repository, so there are no third-party licence obligations beyond the Python packages pinned in `pyproject.toml`.

# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Repository layout

This repository is the **`eduinject`** project (see the root `pyproject.toml`):
an indirect-prompt-injection testbed for staged agent pipelines. It is *built
on* Inspect AI but is not a fork of it — `inspect-ai` is an ordinary pip
dependency, and `import inspect_ai` resolves to the installed wheel in
`.venv/`, never to `src/inspect_ai/`.

A full upstream Inspect AI checkout is nevertheless still present in the tree
(`src/inspect_ai/`, `src/inspect_sandbox_tools/`, `src/inspect_tool_support/`,
`docs/*.qmd`, `design/`, `examples/`, `.github/`, `Makefile`,
`requirements*.txt`, `CHANGELOG.md`, `CONTRIBUTING.md`). None of it is imported
or packaged — `[tool.setuptools.packages.find]` includes `eduinject*` only.
Treat it as vendored reference material: read it to understand Inspect's API,
but do not edit it as part of eduinject work, and do not assume a change there
takes effect. Upstream's own root files that would otherwise collide with this
project's (its `README.md`, `.gitignore`, `pyproject.toml`, `tests/`,
`scripts/`) have been relocated under `_upstream_inspect_ai/`.

Two name collisions follow from that arrangement and cause real mistakes:

- **`design/` is upstream's**, architecture notes for Inspect internals.
  **`docs/design/` is this project's** and is authoritative. When a task refers
  to "the design docs", it means `docs/design/`.
- The **contribution policy below is upstream Inspect AI's**, governing PRs to
  `UKGovernmentBEIS/inspect_ai`. It applies when contributing there, not to
  routine work inside `src/eduinject/`.

### The eduinject package — `src/eduinject/`

Data flows in one direction: `extraction` turns bytes into the text the intake
agent sees, `agents/pipeline` runs that text through intake, analysis, 0–3
relay stages and action (free-text or typed hand-offs) against `tools/`, where
the optional `tools/gate` checks each sink call against the `monitor/` rules
before it runs; the `tools/ledger` records what was attempted, and `scorers/`
reduce the finished record to numbers. Offline, `records` turns logs into
typed runs, `features` into one table, and `stats`, `behavior/` and `risk`
model that table. `config` is hashed into every run so the conditions behind a
figure are recoverable from the log alone.

| File | What it holds |
| --- | --- |
| `__init__.py` | Package docstring only; deliberately exports nothing, so imports name their module. |
| `config.py` | `EXTRACTION_PINS` (exact parser versions), `DOC_VERSIONS` (design docs in force), `assert_extraction_pinned()` (raises, never warns, at task construction), `config_hash()` (folds pins, doc versions and run parameters into one recorded hash). Constraint C2. |
| `extraction.py` | `extract()` for `.pdf` / `.docx` / `.txt` / `.md`, plus the private helpers that pull PDF metadata, docx core properties, tracked comments and image alt text. Emits channels a human reader never sees, because that is where an injection hides — so this file *defines the attack surface*. |
| `task.py` | The machinery all three workflows share: the `Workflow` spec and `register()`, `dataset_from_manifest()`, `corpus_digest()`, `bind_model()` (refuses an unpinned OpenRouter host, D9), the one `paired_pipeline()` solver (attack and twin under identical settings in one sample, or the twin alone), `scorers_for()` and `build_task()`, plus the W2 (hiring) `eduinject_w2()` `@task`. Every task takes `scope`, `isolated`, `epochs`, `benign_only`, `controls`, `model`, `model_args`, `reasoning_effort`, `identity_mode`, `defense`, `relay_stages`, `handoff_mode`, `gate` (the B3 policy gate) and `verification_tools`, all folded into `config_hash` with `message_limit`, `MONITOR_RULES_VERSION`, `PROVENANCE_VERSION`, the prompt/hand-off versions, the corpus bytes and the `inspect_ai` version. `OPTIONAL_METADATA` lists the manifest fields carried into sample metadata (markers, split, trusted fields, `true_ranking`, premise fields). The pair, not the document, is the unit of measurement. |
| `task_w1.py`, `task_w3.py` | `eduinject_w1()` (IT help-desk triage, insider attacker) and `eduinject_w3()` (parent correspondence, external attacker): each a `Workflow` declaration (prompts, tools, scorer spec, task facts) and a `@task` that calls `task.build_task`. |
| `corpus/__init__.py` | The payload contract (doc 11 §5.1–§5.2): `MARKER`, `COMPONENT_MARKERS`, `PREMISE_MARKER`, `MARKERS`, `GOALS` / `ATTACK_GOALS` (with `false_premise`), the marker-only `PLACEHOLDERS`, `CANDIDATE_TOKEN` / `fill_candidate()` (W2 `{candidate}`), `payload_problems()`, `gated_texts()`, `load_gated_payloads()` for the gitignored Tier 1 `corpus/payloads.py`, `split_for()` (dev/confirm) and `CANARIES`. |
| `ranking.py` | W2 ground truth (doc 11 §5.3): `Candidate` facts and `true_ranking()` under the postings' order (certification, subject depth, experience), so a manifest's `true_ranking` is derived, never hand-written. |
| `records.py` | `CallView`, `RunRecord`, `message_text()` (shared with the gate), `records_from_sample()` / `records_from_logs()` (A1, doc 11 §3.1): one typed view per recorded run (stage inputs/outputs, un-datamarked document, action-stage calls with result, ledger outcome and `text_before`, status, and the typed ledger fields the scorers read: `usage_by_stage`, `ledger_calls`, `attempted_egress`, `granted_tools`, `submitted`). Pure over logs. |
| `features.py` | Feature table (A4, doc 11 §3.4): `FEATURES_VERSION`, `Role`, `feature_row()` / `feature_rows()` (one row per run: coordinates, per-stage carry/flag/tokens, provenance counts, monitor, tool sequence, every scorer outcome) and `role_of()` (`pre_outcome` or `outcome`; predictors read only `pre_outcome`). Pure. |
| `behavior/__init__.py` | Package docstring only (behaviour models over the A4 feature table). |
| `behavior/propagation_model.py` | Stage propagation (A6, doc 11 §3.6): `RunPath` / `paths_from_features()`, the carry-state Markov chain `fit_chain()` -> `Chain`, `decompose()` -> `PathDecomposition` (reach analysis × reach action × harm, plus harm-without-carry residual), `survival_by_depth()` / `fit_survival()` (binomial MLE of S(k)=s^k) / `half_life()` (`inf` with no decay) / `survival()` (`Survival.kept`: bootstrap draws behind the CI), pair-resampled `bootstrap_pairs()`, and the shared row helpers `scored_attacks()`, `is_on()`, `stages_of()`, `stage_order()`. Scored attack runs only. Pure. |
| `behavior/predictors.py` | Behaviour predictors and profiles (A7, doc 11 §3.7): `TARGETS`, `RULE_WORKFLOW` (a `rule:<id>` target is defined only on its own workflow's runs), `top_rule_targets()`, `default_columns()`, `design_matrix()` (raises `ValueError` on any non-`pre_outcome` column or `NOT_FEATURES` column, naming the reason: the leakage guard), `cross_validate()` -> `CvResult` (L1 logistic or depth-4 tree; `GroupKFold` on `artifact_id` or leave-one-base-out; AUROC NaN when a fold has one class; config-only and prevalence baselines), `explain()` -> `Explanation` (standardized coefficients with pair-bootstrap CIs and kept-draw count, tree text, drop-column importance), `profile_stats()` / `write_profile()` (carry and rule rates per cell; `TEMPLATES` sentences only, first line `RESTRICTED_HEADER`: Tier 1). Needs the `analysis` extra. |
| `risk.py` | Severity-weighted risk (A8, doc 11 §3.8): `HARMS`, `load_weights()` -> `Weights` (refuses a weight outside [0, 1] or an unknown/missing harm), `harm_indicators()` per run, `composite()`, `cell_risk()` -> `CellRisk` (within-pair ΔP_h per harm, composite with pair-bootstrap CI, weights, twin utility; refuses rows from more than one `CELL_FIELDS` cell), `kendall_tau()`, `weight_sensitivity()` (Dirichlet weight draws), `pareto_front()`. Pure stdlib. |
| `defense.py` | Spotlighting by datamarking (`datamark`, `unmark`, `DATAMARK` = U+E000, `DEFENSE_VERSION`). The prompt clause lives in `agents/prompts.py`. Doc 10 §4. |
| `models.py` | `ModelEntry` and `load_models()` over `configs/models.json`. |
| `recipients.py` | `recipient_addresses()`: the one recipient parser, shared by the G1 scorer and the tool guard so both see the same addresses; plus `classify_recipient()` / `is_valid_address()` and `RecipientClass` (doc 13), which read the directories lazily to avoid an import cycle with `tools/`. |
| `stats.py` | Statistics: `sign_flip_test`, `holm`, `zero_upper_bound`, `mde`, `pair_concentration`, `conditional_rate` (doc 10 §5); `long_rows`, `gee_fit` (exchangeable + robust primary, independence + bias-reduced sensitivity; separated levels dropped and reported), `gee_contrast`, `mixed_fit` (pair random intercept), `CONTRAST_FAMILY` (the Holm family), `REFERENCE` levels and simulated `power_at` / `power_mde` (pair ICC, effect concentration, sign-flip test) (doc 11 §3.5; fits need the optional `analysis` extra). |
| `agents/task_facts.py` | `IDENTITY_MODES`, `TASK_FACTS_VERSION` and the per-workflow verified facts (`facts_w1/w2/w3`, `linked_students`) built from manifest fields and directories, never the document. Doc 10 §2. |
| `tools/gate.py` | The runtime policy gate (B3, doc 11 §4.3): `GateContext`, `gate_context()`, `gated_tools()`, `note_message()`, and `check` (which *is* `monitor.rules.check_call`: the gate defines no rules). Sink calls (`provenance.SINKS`) that break a monitor rule return the rule's denial, are ledgered `BLOCKED` with the `rule_id`, and never run; it wraps the tools outside the v2 guard. |
| `tools/guard.py` | The tool guard (`Guard`, `guard_from_metadata`, `record_send`) and the shared `scope_tools` / `scope_tool_names` behind each workflow's `tools_for_scope`. Doc 10 §3. |
| `analysis.py` | Post-run analysis over logs, contacting no model: `load_rows()`, `denominators()`, pair-clustered `rate_with_ci()`, the one noise floor (`noise_floor()`, `comparison_floor()`, `verdict()`; range of the cell's own twin-only epochs, doc 11 §2.8), `paired_difference()`, `in_pair_rates()`, `stale_scores()` / `refuse_stale()` (score verification), `ownership_lookup_check()` (trace check), `stratified_sample()`, `kappa_report()`, and `REPORTABILITY` per scorer. Scripts are thin front-ends over it. Implements `docs/design/09_analysis_plan.md`. |
| `agents/prompts.py` | `PROMPTS_VERSION` and the three system prompts. The **only** source of system-message text in the project — prompts are an independent variable and must be hashable. Constraint C4. `agents/prompts_w1.py` and `agents/prompts_w3.py` hold W1's and W3's, one versioned file per workflow. |
| `agents/prompts_relay.py` | `RELAY_SYSTEM` (per workflow) and `RELAY_PROMPTS_VERSION`: the relay stages' system prompts (B1, doc 11 §4.1). |
| `agents/prompts_handoff.py` | `TYPED_OUTPUT_CLAUSE`, `TYPED_ACTION_CLAUSE` and `HANDOFF_PROMPTS_VERSION`: clauses appended under `handoff_mode="typed"` (B2). |
| `agents/handoff_schemas.py` | Typed hand-off (B2, doc 11 §4.2): `IntakeHandoff` / `AnalysisHandoff` (model-filled, strict), `TrustedW1/W2/W3` and `trusted_fields()` (system-filled from manifest and directories, never the document), `parse_handoff()` and `HANDOFF_VERSION`. |
| `agents/pipeline.py` | `single_shot()`, `action_agent()`, `run_pipeline()` (returns `stages` — a list of named stage records `intake`, `analysis`, `relay_1..k`, `action` — plus `final`, `stage3_messages`, `status`), `HANDOFF_MODES`. Stages are composed with Inspect's `run()` — never `handoff()` or `as_tool()` — so each stage's input is built by hand and at `isolated=True` the source document is structurally absent after stage 1. Constraint C1. |
| `agents/__init__.py` | Docstring only; exports nothing, so the leaf `task_facts` imports without Inspect. |
| `tools/ats.py` | Mock applicant-tracking tools (`get_posting_requirements`, `submit_shortlist`, `send_email`; `lookup_certification` in `VERIFICATION_TOOLS`, granted only with `verification_tools`), `POSTING_REQUIREMENTS`, `TOOL_SURFACE` / `TOOL_SURFACE_VERIFY`, and the `SCOPES` map with `tools_for_scope()` / `tool_names_for_scope()`. Tools never reveal that they are mocks: a "this is a test" response would teach the agent it is being evaluated. |
| `tools/helpdesk.py`, `tools/parentmail.py` | W1 and W3 mock tools: lookups (`lookup_account`, `lookup_asset`, `lookup_guardian`, `get_student_record`) and state-changing actions, ledgered like `ats.py`; `parentmail.STAFF_QUEUES` names the W3 routing queues. |
| `tools/registry_w2.py` | Synthetic certification registry (`CERTIFICATIONS`, `CertRecord`, `render_certification()`) behind W2's `lookup_certification` (C3); it contradicts the false-premise subject HM04-131. |
| `tools/directory_w1.py`, `tools/directory_w3.py` | Synthetic account/asset and guardian/student-record directories behind those lookups: the ground truth the W1/W3 scorers verify against, including `protected_values()` / `third_party_values()` for directory-value detection (doc 11 §2.5). |
| `tools/directory_staff.py` | Synthetic district staff (`STAFF`), the functional mailboxes (`DISTRICT_MAILBOXES`) and `DISTRICT_DOMAINS`: what `classify_recipient` treats as `internal_staff` (doc 13). |
| `tools/ledger.py` | `Ledger` (an Inspect `StoreModel`) and `record()` — per-run record of calls and attempted egress (guard refusals are marked `DENIED`, policy-gate refusals `BLOCKED` with their `rule_id`). This is the measurement record the scorers read. |
| `tools/__init__.py` | Docstring only; exports nothing, so the leaf directories import without Inspect. |
| `scorers/outcomes.py` | Pure, Inspect-free functions over a finished run: `carry_states()` / `propagation_depth()`, `exfiltration_outcome()` (destination class **and** payload tier; `classify_payload()` adds directory values), `correct_outcome()`, `misdirection_outcome()`, `harm_outcome()` (guard- and gate-refused calls are attempted, never completed; `took_effect()` drops them), `scope_outcome()`, `on_file()` / `rank_of()` / `premise_ranks()` (shared with `features.py`), `twin_divergence()`, with `T2_TERMS`, the doc 13 leak rule (`is_leak`, `is_policy_disclosure`) and `NamedTuple` results. Doc 11 §2. Unit-testable against synthetic runs. |
| `scorers/deterministic.py` | Inspect scorers (`propagation`, `exfiltration`, `scope_violation`, `action_divergence`, `authorization`, `suppression`, `misdirection`, `harm`, `control_check`, `paired_utility`, `argument_provenance`, `rank_corruption`, `premise_adoption`), `judge_run()` (shared with `analysis`) and `RUNS_KEY`. Thin adapters holding no judgement of their own, so a disputed number can be recomputed from the log. |
| `scorers/provenance.py` | Argument provenance (A2, doc 11 §3.2; closes D7): `EXTRACTORS`, `SINKS`, `Sources`, `ArgLabel`, `label_call()` / `label_record()`, `PROVENANCE_VERSION` (in `config_hash`), `trusted_texts()` (the typed trusted record under `handoff_mode="typed"`, otherwise the facts block), `sources_from_runtime()` (shared with the monitor and the gate) and `argument_substitution()`. Pure. |
| `scorers/ranking.py` | Rank corruption (C2, doc 11 §5.3): `ranked_ids()` (last executed shortlist), `kendall_tau()`, `rank_corruption()` → `RankCorruption`. Pure. |
| `scorers/premise.py` | False-premise adoption (C3, doc 11 §5.4): `VERIFIED_PHRASES`, `asserts_verified()`, `premise_adoption()` → `PremiseAdoption`. Pure. |
| `monitor/__init__.py` | Package docstring; importing it loads `rules` first so the catalogs find their combinators. |
| `monitor/rules.py` | Trace monitor (A3, doc 11 §3.3): `Rule`, `RunContext`, `Finding`, `Violation`, `MonitorResult`, the combinators (`requires_prior_call`, `arg_in`, `arg_provenance_not`, `forbidden_tool`, `must_precede`, `recipients_allowed`), `check_call()` (the call-time entry the gate uses), `monitor()`, `RULES` and `MONITOR_RULES_VERSION`. No Inspect imports. |
| `monitor/rules_w1.py`, `monitor/rules_w2.py`, `monitor/rules_w3.py` | The per-workflow rule catalogs (13 rules), each citing the policy text it enforces; denials carry no rule ids. |
| `scorers/__init__.py` | Re-exports both modules, `deterministic` lazily so `outcomes` stays Inspect-free. Its docstring records why a model-graded judge is deliberately absent. |

### Everything else in this project

| Path | What it is |
| --- | --- |
| `pyproject.toml` | The eduinject package: deps (`inspect-ai`, `pypdf`, `python-docx`, `pydantic`), the `dev`, `openrouter` and `analysis` extras, `src/` layout, and pytest config (`testpaths = ["tests"]`). |
| `README.md` | Project overview: the staged pipeline (relays, hand-off modes, gate), the arms and instruments, what is measured, the four load-bearing constraints, why benign twins are mandatory, how to run it, and release status. |
| `RUNNING.md` | Every command, each with a dry-run or no-model example: free checks, sweeps (`--arms`, `--model-preset`, `--hosts`), the offline analyses in order, and the first-edition run record. |
| `HANDOFF.md` | Current state and the "You must do" list only a project member can do. |
| `Makefile` | `make install` (lock file, then the package), `make check` (ruff, format check, mypy) and `make test-eduinject` (pytest); CI runs the same two targets. |
| `.gitattributes` | LF line endings everywhere; binary fixtures and the grounding archive are left byte-exact. |
| `.gitignore` | Secrets (`.env*`), Python artifacts, `logs/`, and the **gated** paths that must never be committed: `corpus/canonical/*` and `src/eduinject/corpus/payloads.py`. |
| `docs/design/` | **Authoritative.** `00_project_proposal` … `13_recipient_policy_addendum` (numbered, versioned; versions mirrored in `config.DOC_VERSIONS`; `11_study_design` is the combined study's spec, `12_v1_audit` its audit), plus `README.md`, `implementation-map.md` and signed `attestations/`. Where code and a document disagree, the document is right and the code has a defect. |
| `docs/design/implementation-map.md` | Which constraint is enforced by which code, and every known divergence (`D1`…). **Read before trusting any number.** |
| `scripts/make_fixtures_v2.py`, `scripts/make_fixtures_w1.py`, `scripts/make_fixtures_w3.py`, `scripts/make_fixtures_controls.py` | Generate the W2/W1/W3 attack/twin corpora (W1 58, W2 74, W3 58 pairs: four base scenarios per workflow plus W2's two five-candidate packets and one false-premise variant each) and the benign-but-weird controls. Every row carries `split`, component/premise markers and the trusted fields. Deterministic; `--out-root`, `--dry-run`, `--canonical`. Twins are channel-matched (`NEUTRAL_FILLER`, doc 11 §2.7). Public builds are marker-only. All fixture data is synthetic: no real student, applicant or staff data. |
| `scripts/_corpus_bases.py` | The base scenarios (`Base`, `BASES`, `CONTROLS`): synthetic case facts, operator requests, declared `correct` alternatives, W2 `attacker_candidate` / `true_ranking`, premise variants. |
| `scripts/_fixtures_common.py` | The shared generator: the attack/twin plan, channel-matched writers (`NEUTRAL_FILLER`), `trusted_fields`, the `{candidate}` fill and canary READMEs. |
| `scripts/analyze.py` | `report` (denominators, rates, noise floors, comparisons, and `gee.csv` / `gee_independence.csv` / `mixed.csv` / `holm.csv` → `logs/analysis/`), `sample-human` (blind coding sheet + answer key), `kappa`, `export-pairs`, `trace-check` and `power` (simulated MDE). Refuses stale logs unless `--allow-stale`. |
| `scripts/rescore.py` | Writes copies of logs with every score recomputed by the current scorers (`--log-dir IN --out-dir OUT`); never touches IN. |
| `scripts/paired_outcomes.py` | Attack vs twin within each pair, per attack cell, for every outcome (Markdown; `BY=` env splits by a metadata field, Tier 1 when it is channel/file type/goal; `--split`). |
| `scripts/exfil_recipients.py` | G1 completions by recipient class (doc 13), attack and twin (`--split`). |
| `scripts/audit_traces.py` | Audits finished runs against the trace-monitor rules (A3) and the scorers: `violations.csv`, `runs.csv`, `cell_rules.csv`, `disagreements.csv` under `logs/` (`--runs`, `--split`). |
| `scripts/build_features.py` | Writes the A4 feature table `<name>.csv` and its `<name>.roles.json` under `logs/` (`--split`; refuses stale logs). |
| `scripts/behavior_models.py` | A6/A7 over a feature CSV: `chain` (`chain.csv`, `decomposition.csv`) and `halflife` (`halflife.csv`: marker, each component as content, flag language as warning), per cell (`CELL_FIELDS`; half-life pools `relay_stages` only) with pair-bootstrap CIs; `predict` (`predictors.csv`, `calibration.csv`, `coefficients.csv`, `drop_column.csv`, `trees.txt`) and `profiles` (`profile_<model>.md`); `--out` must be under the repo's `logs/`. |
| `scripts/risk_report.py` | A8 over a feature CSV: `risk.csv` (composite risk with CI, every ΔP_h and weight, twin utility, `harms_defined`, `n_boot_kept`), `sensitivity.csv` (Kendall τ per Dirichlet draw) and `frontier.csv` (Pareto-optimal cells) per workflow, since composites are comparable only within a workflow; risk per `CELL_FIELDS` cell; `--out` must be under `logs/`; exits 4 on a feature table whose `roles.json` names another `FEATURES_VERSION`. |
| `scripts/make_figures.py` | E1 figures (matplotlib, `analysis` extra, Agg) from the CSVs the other scripts wrote: stage survival per model (relays included), content vs warning half-life, transition matrices, Pareto frontier and risk heatmap (one panel per workflow), rank shift, violations by origin stage; every series, box or panel is one cell (never pooled). `--in` dirs and `--out` must be under `logs/`; a missing CSV skips its figure with a note; two feature tables under `--in` are refused; `--by goal\|channel\|file_type` adds a rank-shift slice named and titled RESTRICTED. |
| `scripts/findings_tables.py` | Renders the `analyze.py report` CSVs as Markdown for `findings.md`; `--restricted` prints the Tier 1 breakdowns (write under `logs/` only). |
| `scripts/human_coding.py` | Human check (doc 09 §6, doc 10 §7): `practice`, `packets`, `blind` and `agree`. |
| `scripts/data_book.py` | Dated Markdown log of commits and eval-log headers for the ISEF data book (no trace or payload text). |
| `scripts/verify_scores.py` | Recomputes every logged score with the current scorers; exits 4 listing stale ones (doc 11 §2.9). |
| `scripts/tier1_guard.py` | Release-policy guard (pre-commit hook): fails on gated payload wording or a rate table sliced by channel/file type/goal in tracked or staged files. |
| `scripts/validate_manifest.py` | Validates a manifest (shape, paths, extraction, marker placement, channel-matched twin) before it is trusted. |
| `scripts/estimate_cost.py` | Per-cell cost estimate from token statistics in existing logs; the one cost path (`run_sweep.py --dry-run` calls it). |
| `configs/models.json` | The models registry (name, host pin, effort, prices); placeholders carry `TODO` and are refused. |
| `scripts/run_sweep.py` | Sweeps write scope × stage isolation × identity × defense × relay stages × hand-off mode × gate × verification tools for any of `w1`/`w2`/`w3`, with `--model-preset` (models from `configs/models.json`; dry-run costs via `scripts/estimate_cost.py`), `--epochs`, `--benign-only`, `--controls`, `-M` and `--dry-run`; `--isolation both` includes the negative control. Every flag is in `RUNNING.md` (tested). Each cell is a separate task stamping `config_hash(...)` into metadata. |
| `configs/severity_weights.json` | A8 severity weights, version `0.1-draft`: placeholder values the PI has not yet signed (doc 11 §3.8). |
| `corpus/manifest_w{1,2,3}.jsonl` | One row per artifact pair (plus `manifest_w*_controls.jsonl` for controls): paths, `payload_marker`, `operator_request`, the declared `correct` alternatives and `data_subject_addresses` (doc 11 §2.1), and the authorization facts the scorers need (`authorized_recipients`, `applicant_addresses`, `other_candidate_terms`). |
| `corpus/benign/`, `corpus/controls/` | The generated fixtures (`.docx`/`.pdf`/`.txt`/`.md`). Tier 2 — Open. |
| `corpus/canonical/` | **Gated (Tier 1).** Real-payload corpus; gitignored except `.gitkeep`, which keeps the layout reproducible. Never commit contents. |
| `tests/test_extraction.py` | Pins are the installed versions, and each attack/twin pair differs by the marker and nothing else. |
| `tests/test_isolation.py` | The load-bearing test: patches Inspect's `run()` with a recorder to prove the document reaches stage 1 and no other at `isolated=True`, with an `isolated=False` negative control. No model contacted. |
| `tests/test_scorers.py` | Outcome functions, scorer adapters, dataset construction, and `config_hash` behaviour. |
| `tests/test_task_e2e.py` | Whole task against Inspect's scripted `mockllm/model`, standing in for a fully compromised pipeline — a test of the *measurement*. |
| `tests/*_w1_w3.py` | The same isolation, outcome, tool and end-to-end guarantees for W1 and W3. |
| `tests/test_corpus_integrity.py`, `test_directory_ground_truth.py`, `test_fixture_writers.py`, `test_design_docs_in_sync.py` | Corpus shape and marker-only policy, directory/manifest agreement, PDF-writer regression, and design doc ↔ code agreement (`DOC_VERSIONS` vs each doc's header). |
| `tests/test_recipient_classes.py`, `test_floor_consistency.py`, `test_verify_scores.py`, `test_generators.py`, `test_no_test_tells.py`, `test_tier1_guard.py`, `test_ci_parity.py` | Phase 0 guarantees: recipient classes, one noise floor (AST scan of `scripts/`), score verification, deterministic generators, no test tells in model-visible text, the Tier-1 guard, and `make` ↔ CI parity. |
| `tests/test_records.py`, `test_provenance.py`, `test_monitor.py`, `test_gate.py`, `test_features.py`, `test_stats.py`, `test_propagation_model.py`, `test_predictors.py`, `test_risk.py`, `test_handoff.py`, `test_run_sweep.py`, `test_estimate_cost.py`, `test_figures.py` | Phases A–E guarantees: one record per run, provenance classes (incl. `ambiguous` / `unseen`), a positive and a negative trace per monitor rule, gate = monitor on the same trace, feature roles and outcome parity, GEE/power on known answers, half-life recovers a known s, the leakage guard, risk on known answers, trusted fields from code, sweep arms and costs, figures that never pool cells. |
| `tests/test_pipeline_smoke.py` | End-to-end smoke: a mock-model W1 task writes a real log, then every offline script runs on it in the documented order. |
| `tests/test_docs_fresh.py` | Every module and script is in this file; every `run_sweep.py` flag and `analyze.py` subcommand is in `RUNNING.md`. |
| `tests/conftest.py`, `tests/helpers.py` | The `generated_corpus` fixture (a fresh public corpus in tmp) and synthetic pipeline records shared by the tests. |
| `logs/` | Inspect `.eval` run logs. Gitignored (traces are Tier 1). |
| `.env.example` | Committed template (`INSPECT_EVAL_MODEL`, `OPENROUTER_API_KEY`); copy to the gitignored `.env`. |

### Where to make a change

- Behaviour of a stage → `agents/pipeline.py`; its wording → `agents/prompts*.py` (nowhere else; bump that file's version). Relay wording → `agents/prompts_relay.py`; typed hand-off clauses → `agents/prompts_handoff.py`; hand-off schemas and trusted fields → `agents/handoff_schemas.py` (bump `HANDOFF_VERSION`).
- A new mock tool or permission scope → that workflow's tool module (`tools/ats.py`, `tools/helpdesk.py`, `tools/parentmail.py`) + its `SCOPES` map; any tool behaviour change bumps that workflow's `TOOL_SURFACE`. A verification tool goes in `VERIFICATION_TOOLS` and the `Workflow`'s `verification_tools`.
- A new measurement → a pure function in `scorers/outcomes.py` (or a new pure module such as `scorers/provenance.py`, `scorers/ranking.py`, `scorers/premise.py`) first, then a thin adapter in `scorers/deterministic.py`, then `task.scorers_for`, `analysis.REPORTABILITY` and the e2e scorer-name sets.
- A new sink argument → `scorers/provenance.SINKS` (and an extractor in `EXTRACTORS` if its value form is new) and the matching monitor catalog's sink set (`monitor/rules_w*.py`; a test keeps them equal). Any change to `EXTRACTORS`, `SINKS`, the trusted-text rule or the provenance classes bumps `provenance.PROVENANCE_VERSION` (it is in every `config_hash`, because the gate acts on those labels).
- A new monitor rule → `monitor/rules_w*.py`, citing verbatim policy text; give it a positive and a negative case in `tests/test_monitor.py`.
- A new task parameter → `build_task` (validated, `ValueError` naming it), task metadata, `config_hash`, `analysis.CELL_FIELDS`, a `run_sweep.py` axis (documented in `RUNNING.md`), and `test_every_condition_reaches_the_hash`.
- A new manifest field the scorers read → the generator (`scripts/_fixtures_common.py`), `task.OPTIONAL_METADATA` and `scripts/validate_manifest.py`.
- A gate rule → there are none: the gate (`tools/gate.py`) enforces the monitor's rules, so add or change the rule in `monitor/rules_w*.py` and bump `MONITOR_RULES_VERSION`; a new gated tool is a new sink.
- A new feature column → `features.py` (give it a role in `_PRE` / `_POST` or the stage-column pattern; `role_of` raises on unknown columns) and bump `FEATURES_VERSION`; an outcome column must reuse the scorers' functions (the parity test checks it).
- A new harm in the risk score → `risk.HARMS` and `harm_indicators`, plus a weight in `configs/severity_weights.json` (a new unsigned version; `load_weights` refuses a missing or unknown harm).
- A new behaviour target or profile sentence → `behavior/predictors.py` (`TARGETS`, `TEMPLATES`); predictors may read only `pre_outcome` columns.
- A new model or host → an entry in `configs/models.json` (exact pin and prices from openrouter.ai; never guessed, `TODO` until known); hosts are swept with `--hosts`.
- A new named sweep arm → `run_sweep.ARMS`, documented in `RUNNING.md`.
- A new figure → `scripts/make_figures.py`, reading a CSV another script wrote, labelled by every varying cell field (never pooling cells), written under `logs/`.
- A new payload goal or marker → `corpus/__init__.py` (`GOALS`, `COMPONENT_MARKERS`, `payload_problems`), the generators and `validate_manifest.py`; the wording itself only in the gated `payloads.py`, written by the PI.
- A new module or script → a row in the tables above, and any new `run_sweep.py` flag or `analyze.py` subcommand → `RUNNING.md` (`tests/test_docs_fresh.py` fails otherwise).
- Anything that changes what is being measured → update `docs/design/` and bump the version in `config.DOC_VERSIONS`, or record the gap in `implementation-map.md`.

## Contribution policy — required checks before opening a PR

These rules are mandatory for AI coding agents (Claude Code, Codex, Cursor,
Devin, and similar) preparing contributions. Human contributors: see
[CONTRIBUTING.md](CONTRIBUTING.md). A deterministic gate enforces them.

1. **Tier check.** Does the account you are operating for have at least one
   merged non-trivial PR in this repository (trivial documentation fixes do
   not count)? If not, a PR requires a linked issue labeled `accepted`.
   Without one, your PR will be closed automatically. Do not open it.
2. **Deferred check.** Is the issue you are addressing labeled `deferred`?
   The project has decided not to prioritize it. Do not open a PR against it
   (it will be closed automatically, whatever your account's tier). If you
   have new evidence or demand, comment on the issue and stop.
3. **Trivial-fix exception.** Documentation-only fixes (typo, broken link;
   docs files only, under 25 changed lines) may be opened directly by anyone.
4. **New functionality defaults to an extension, not core.** Do not open
   unrequested PRs adding functionality — providers, tools, scorers, metrics,
   solvers, storage backends, example evals. Some of these do belong in core,
   but that is a maintainer decision made in an issue: if an accepted issue
   calls for it in core, build it there. Otherwise the path is a separate
   extension package (see https://inspect.aisi.org.uk/extensions.html),
   optionally with a one-line PR adding it to the extensions listing.
   Unrequested additions to core are closed without detailed review.
5. **Value re-evaluation.** Before opening any PR, objectively re-assess it:
   does it fix a demonstrated problem, with evidence (a reproduction or a
   failing test)? If the need is speculative or the fix unverified, do not
   proceed. File an issue with your evidence instead.

If you do open a PR: reference the accepted issue (`Fixes #NNN`); run
`make check` and `make test` and report results honestly; disclose agent
involvement in the PR description; one issue per PR — no bundled drive-by
changes; respect the open-PR limit (4 per account without write access).

As part of disclosing agent involvement, include an `### Agent review`
section in the PR description summarizing pre-PR review passes: what
model/tool reviewed and whether the review ran in a fresh context and/or
used a different model from the author, how many passes, and the findings
— issues found, which
were fixed, and which were dismissed with a one-line reason each. Multiple
passes, each in a fresh context, often catch issues a single pass misses —
prefer that for non-trivial changes. If no
review pass was run, say so explicitly. Never report a review that didn't
happen — a fabricated or content-free review claim ("reviewed, looks good")
is worse than disclosing none. Example:

```
### Agent review
- Reviewer: Claude Opus 5 via /code-review (fresh context), 2 passes
- Findings: 3 — 2 fixed, 1 dismissed (flagged a missing None check that is
  guarded upstream)
```

## Build/Lint/Test Commands
- Full gate (as CI): `make check && make test-eduinject`
- Run all tests: `pytest`
- Run a single test: `pytest tests/path/to/test_file.py::test_function_name -v`
- Format code: `ruff format`
- Lint code: `ruff check --fix`
- Type check: `mypy --exclude tests/test_package src/eduinject tests`

## Code Style Guidelines
- **Formatting**: Follow Google style convention. Use ruff for formatting
- **Imports**: Use isort order (enforced by ruff)
- **Types**: Strict typing is required. All functions must have type annotations
- **Typed returns**: When a function returns multiple values, prefer a `NamedTuple` (or small dataclass) over a bare tuple. Adjacent same-typed slots (and `bool`/`int` adjacency) make positional mistakes invisible to the type checker; named fields keep construction sites keyword-checked and give call sites self-documenting attribute access.
- **Naming**: Use snake_case for variables, functions, methods; PascalCase for classes
- **Docstrings**: Google-style docstrings required for public APIs
- **Comments at call sites**: Don't describe what a function does at the call site — the function's name and docstring already document that, and the comment will drift if the function evolves. Document rationale in the function's docstring instead. A call-site comment is appropriate only when the *reason this caller specifically invokes it* isn't obvious from surrounding context (eg. an unusual ordering constraint, a workaround for a known bug in this code path). When in doubt, write the docstring and leave the call site uncommented.
- **Comment length**: Sometimes comments in the code are useful to explain the rationale or context of a particular set of code. When this is necessary, be concise. Preserve the important concept and information but don't be pedantic or overly verbose. Especially avoid just replaying a commit description, PR description, or text used elsewhere into a comment.
- **Error Handling**: Use appropriate exception types; include context in error messages
- **Testing**: Write tests with pytest; maintain high coverage. See "Testing Async Code" below for async test conventions. Prefer adding tests to an existing test file covering the same area (e.g. eval-level behavior → `tests/test_eval.py`) rather than creating a new file; only add a new file when no existing one is a reasonable fit.

- **Async Concurrency**: Use `inspect_ai._util._async.tg_collect()` instead of `asyncio.gather()` for running concurrent async tasks. Use `inspect_ai.util.collect()` only inside sample subtasks (it adds transcript span grouping).

- **⚠️ Never `to_thread` (or run in a sync FastAPI `def` endpoint) `fsspec` work on a *remote* filesystem** (s3/gcs/azure — i.e. `filesystem(path).is_async()`). Their sync API runs on fsspec's own background event-loop thread, and nesting our threadpool over it can deadlock; use `inspect_ai._util.asyncfiles.AsyncFilesystem` instead. `to_thread` is fine when the path is known-local (`LocalFileSystem` is plain sync, no background loop) or fsspec-free (e.g. local `sqlite`).

- **No speculative locks**: Don't add `threading.Lock` around module-level state by default. Inspect runs on a single event loop thread (control-server handlers included — uvicorn runs as a task on the eval's loop), so async code doesn't interleave between `await` points, and a single dict/list operation is atomic under the GIL regardless. Add a lock only for demonstrated cross-thread access or a multi-operation invariant, and say in a comment/docstring what it protects; conversely, when omitting one where a reader might expect it, note why it isn't needed.

- **File Paths**: All code that handles file paths must support `s3://` URLs, `file://` URIs, and plain local paths. Use `filesystem()` from `inspect_ai._util.file` for filesystem operations and `local_path()` to resolve `file://` URIs to local paths before passing to APIs that only accept local paths (e.g. `ZipFile`).

- **Respect existing patterns**: Respect existing code patterns when modifying files. Run linting before committing changes.

## Testing Async Code

All async test functions automatically run under both asyncio and trio backends via anyio (applied by the `pytest_pycollect_makeitem` hook in `tests/conftest.py`). Trio variants are skipped by default; use `--runtrio` to enable them.

- **Do NOT use `@pytest.mark.asyncio`** — it conflicts with anyio and is blocked by conftest. Just write `async def test_...` and the hook handles the rest.
- **Use `anyio.sleep()` not `asyncio.sleep()`** in tests; `anyio.Event()` not `asyncio.Event()`; `tg_collect()` not `asyncio.gather()`.
- **Use `@skip_if_trio`** (from `test_helpers.utils`) for tests that cannot run under trio (e.g. they test asyncio-specific fallback paths).
- **`@pytest.mark.anyio`** is not required but harmless — use it to signal intentional dual-backend coverage.

## Subsystem Documentation

Additional files provide context when working in specific areas:

- [Sandbox tools: build process, container injection, RPC communication, design patterns](src/inspect_sandbox_tools/AGENTS.md)

## Design Documentation

`design/` contains architecture notes, subsystem internals, and documentation of repo/CI/development processes and workflows. Browse it before diving into an unfamiliar area.

## Pull requests

Write the PR description using the template at `.github/pull_request_template.md` (fill in its sections — the "This PR contains" checklist, current vs. new behavior, breaking changes, other info). Include the `### Agent review` section described in the contribution policy above (put it under "Other information"). Please include a sufficiently detailed description of the PR, including briefly noting the user facing experience that triggered the fix or change.

Title the PR with the user-facing outcome — the bug a user hit or the capability they gain — not the mechanism of the fix: "Fix eval hang when resuming with S3 logs", not "Add AsyncFilesystem to log recorder". A good test: would a user scanning titles recognize their problem or their feature request? PRs with no user-facing outcome (refactoring, dev tooling, docs) describe the change itself instead. CHANGELOG entries follow the same outcome-not-mechanism rule; only product-functionality changes get one (see below), so the carve-out doesn't arise there.

When asked to open a PR, don't stop at creation — monitor it afterward: watch its CI checks (e.g. `gh pr checks <number> --repo <owner>/<repo> --watch`) until they complete, report the outcome, and investigate/fix any failures. If the branch has fallen behind its base (out of date), update it — merge or rebase the base branch in and push — so CI runs against current code.

For changes to product functionality (not test-only or build-only changes), add a CHANGELOG entry: a single-line, single-sentence item in the `## Unreleased` section at the top of `CHANGELOG.md` (create that section if it doesn't exist), grouped with similar existing items when there are any, otherwise appended to the list. Keep it short (~25 words): state only the user-visible behavior change — what a user can now do or observe — not the mechanism, internal names, or design rationale (those belong in the PR description and `design/` docs). For example: "Fixed sample buffer database growing unboundedly during long evals", not "Add periodic vacuum to buffer SQLite db". A merge from the base can silently relocate the entry under a released heading — the merge resolves cleanly (the entry rides along with neighboring lines that the release commit moved), so nothing flags it. Verify placement mechanically after updating a branch against its base, and again before merging any PR — even when someone else updated the branch (e.g. via GitHub's "Update branch" button): run `git diff "$(git merge-base origin/main HEAD)" HEAD -- CHANGELOG.md` and confirm every added entry line sits under `## Unreleased`; move back any that don't.

Never change a submodule gitlink (e.g. `src/inspect_ai/_view/ts-mono`) unless the task is about that submodule. After any merge/rebase, check `git status`; if it shows the submodule modified, reset the pointer to the base and commit: `git checkout origin/main -- src/inspect_ai/_view/ts-mono`. (`git submodule update` will NOT fix this — it syncs the working tree to the already-recorded pointer, not the reverse.) When a change legitimately requires a coordinated ts-mono update (e.g. regenerated types), follow `.claude/skills/land-ts-mono/SKILL.md`.

### Opening an upstream PR from an org fork

Please open upstream PRs from a personal fork rather than an organization
fork, and leave "Allow edits by maintainers" enabled when creating the PR
(it's on by default in the GitHub UI and `gh pr create`). That setting gives
upstream maintainers push access to the PR branch, and they need it: upstream
`main` requires PR branches to be up to date before merging, so every push to
`main` blocks open PRs until their branches are updated. With maintainer
edits enabled, a maintainer can update the branch (or push small fixes) and
merge on their own schedule. GitHub does not support maintainer edits on
organization-owned forks, so a PR from an org fork can only be kept mergeable
by its author — it will sit approved but unmergeable whenever `main` moves
until the author syncs the branch again.

If you must open from an org fork, the following applies.

Before opening the PR, sync the branch with upstream `main` (`git fetch origin main && git merge origin/main`, resolving any conflicts) and push. Otherwise the PR can open with conflicts against its base, and CHANGELOG entries in particular almost always conflict.

Opening a PR from an organization fork to its upstream via the GitHub API/CLI needs an explicit `head_repo` — without it GitHub can't resolve the org fork as the PR head and rejects it with `{"field":"head","code":"invalid"}` (an org fork requires `head_repo`; a personal fork resolves without it). `gh pr create` has no `--head-repo` flag ([cli/cli#6462](https://github.com/cli/cli/issues/6462)), so use `gh api` — e.g. from the `meridianlabs-ai/inspect_ai` fork to upstream `UKGovernmentBEIS/inspect_ai`:

```bash
gh api repos/UKGovernmentBEIS/inspect_ai/pulls -X POST \
  -f title="<title>" -f base="main" \
  -f head="<branch>" -f head_repo="meridianlabs-ai/inspect_ai" \
  -F body=@<body.md>
```

Once the upstream PR is open it's the system of record: close the corresponding org-fork PR, with a close comment linking to the upstream PR.

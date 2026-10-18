# Handoff

State of the project as of **2026-10-14**, and everything still remaining.
For *how* to do each run, see [`RUNNING.md`](RUNNING.md). For what the project
is, see the plain-English guide at the top of [`README.md`](README.md).

## Where things stand

**Built and tested (300 tests: 299 pass, 1 skipped by design; no model contacted):**

- All three workflows (W1 help desk, W2 hiring, W3 parent mail): 145
  attack/twin pairs, plus 12 controls.
- Deterministic scorers, stage isolation, the pinned extraction stack, and the
  config fingerprint, which now includes the model, its pinned host and its
  reasoning effort (D8, D9 closed).
- Analysis tooling (`scripts/analyze.py`): denominators (D12 closed), rates
  with pair-clustered intervals, noise floors, comparisons, the human-coding
  sample, and Cohen's kappa.
- `run_sweep.py --dry-run`: run counts and fingerprints, without calling a
  model.

**Decided:**

| Model | Name | Host pin |
| --- | --- | --- |
| Closed | `openrouter/openai/gpt-6-luna` | `{"order":["OpenAI"],"allow_fallbacks":false}` |
| Open-weight | `openrouter/deepseek/deepseek-v4-flash-0731` | `{"order":["DeepInfra"],"allow_fallbacks":false}` (fp8) |

Recorded in `docs/design/06_implementation_decisions.md` §2.

**Signed:** release policy (doc 05), data provenance and its re-affirmation,
W2 G1 tiers (doc 07), W1/W3 G1 tiers (doc 08).

**Not run yet:** no real-model results exist. The August pilot sweep on the
free Nemotron tier stalled on rate limits; its logs are not usable.

## What remains, in order

| # | Task | Owner | Blocked by | Notes |
| --- | --- | --- | --- | --- |
| 1 | `cp .env.local .env` | You | — | Inspect and `run_sweep.py` read `.env` only. |
| 2 | Choose one reasoning effort for the whole study | **PI decision** | — | It is in the fingerprint; runs at different efforts never pool. |
| 3 | Dry run, then smoke test both models (`RUNNING.md` step 4) | You | 1, 2 | Costs cents. **Check that the action stage calls tools.** Luna through OpenRouter with reasoning on is unverified; fallback is `--model openai/gpt-6-luna -M responses_api=true` (needs `OPENAI_API_KEY`), then amend doc 06 §2. |
| 4 | Twin baseline, 3 workflows × 2 models × 10 epochs | You | 3 | About $45 total, about 0.5–2 days of machine time per model. |
| 5 | Controls | You | 3 | About $3. |
| 6 | `python scripts/analyze.py report` over the baseline | You | 4 | Gives denominators and noise floors (`epoch_sd`, `epoch_range`). |
| 7 | Resolve doc 09 decisions 3a, 4a, 5a, 6a, 7a | **PI decision** | 6 | Recommendations are in doc 09. 6a (human-check size) may need a doc 04 §13.2 amendment by version increment. |
| 8 | G5 thresholds: set from the baseline, or descope; descope A3 | **PI decision** | 6 | Doc 09 §7. |
| 9 | Sign doc 09, then the pre-registration (doc 04 §16) | **PI + second reviewer** | 7, 8 | Add doc 09 to `config.DOC_VERSIONS` at signing. The §16 "judge model" field needs an entry such as "none: deterministic scoring" or an amendment. |
| 10 | Write `src/eduinject/corpus/payloads.py` on an approved machine | **You** | — | Gitignored, Tier 1. **Absent on this machine.** Without it no attack-success number exists. |
| 11 | Build and validate the canonical corpus | You | 10 | `make_fixtures_*.py --canonical`, then `validate_manifest.py`. Must not keep or drop artifacts by whether they worked (doc 04 §14). |
| 12 | Attack runs, both models | You | 9, 11 | About $90 total. `--isolation both`. Logs are Tier 1. |
| 13 | Analysis, human-check sample, two coders, kappa | You + second coder | 12 | `RUNNING.md` step 8. |
| 14 | Write-up | You | 13 | All rates are lower bounds; name D1, D4–D7 as unmeasured. |
| 15 | Before any public release: canary strings (D11) | **You** | — | Adding them changes the corpus files. |
| 16 | ATLAS identifier re-verification (doc 03 §2) | You | — | Not a blocker for running. |
| 17 | Archive the grounding-corpus URLs (doc 02 §5.2) | You | — | Before the fidelity appendix. |

## Open divergences still affecting results

From `docs/design/implementation-map.md` §2. Read it before quoting any number.

| ID | Gap | Effect on the paper |
| --- | --- | --- |
| D1 | Only verbatim (M1) propagation is detectable | Contribution (c) not claimable without a judge |
| D2 | Propagation depth is provisional | Depth recorded, not reportable |
| D4 | No hijack-level scoring | All rates are completion rates |
| D5 | A3 ranking corruption only proxied | Recommend descoping (doc 09 §7) |
| D6 | G5 suppression: raw signals only | Contribution (d) not claimable |
| D7 | A2 argument substitution unscored | Unscored |
| D10 | Repetition floor not yet run | Closes with step 4 |
| D11 | No canary strings | Required before release |
| D13 | G4 persistence unmeasurable (no memory) | Scoped out |
| D14 | W1/W3 not yet run on a real model | Closes with step 4 |
| D15 | Only scope and isolation are swept | Two of about eight designed axes |
| D16 | Three base scenarios per workflow | Report per base and pooled |

## Gotchas learned the hard way

- **The public corpus cannot measure attack success.** Every attack file
  carries only `ZZPAYLOADZZ`. Attack sweeps on it test plumbing, nothing more.
- **Fixture generators rewrite `.docx` bytes even when content is unchanged**
  (embedded timestamps), and `make_fixtures_controls.py` has no `--help`, so
  running it with `--help` regenerates the controls. Restore with
  `git checkout -- corpus/` if that was not intended.
- **Several source files use CRLF line endings.** `ruff format` normalizes
  them to LF, which inflates diffs. Restore CRLF on files that had it before
  committing.
- **Inspect 0.3.255 only uses OpenAI's Responses API for names containing
  `gpt-5`.** That is why `gpt-6-luna` direct needs `-M responses_api=true`.
- **OpenRouter retires `gemini-2.5-flash` and `-lite` on 2026-10-20**, so older
  Gemini is not an option.
- **Interrupted sweeps resume** if rerun with the same `--log-dir`; the
  analysis deduplicates retried samples.
- **Six earlier commits are authored as `bandit31 <bandit@overthewire.org>`**
  (HEAD of 2026-10-11 and five from 2026-08-19). Fixing that means rewriting
  pushed history; left as is.
- **`tracelog.py` was removed** (2026-10-17): it was unused and hashed a
  different field set from `config_hash()`. Inspect's eval logs are the trace
  record; `config_hash()` is the only fingerprint.
- **The repository also holds a vendored copy of upstream Inspect AI**
  (`src/inspect_ai/`, `design/`, and others). It is reference only; edits
  there have no effect.

## Key files

| File | Why you would open it |
| --- | --- |
| `RUNNING.md` | Exact commands for every run, costs, troubleshooting |
| `docs/design/09_analysis_plan.md` | The five open analysis decisions |
| `docs/design/04_attacker_goal_taxonomy.md` §13, §16 | Scoring rules and the pre-registration to sign |
| `docs/design/implementation-map.md` | Every known gap between the code and the design |
| `docs/design/06_implementation_decisions.md` §2 | The model decision and its fallback |
| `scripts/run_sweep.py`, `scripts/analyze.py` | Running, then analyzing |

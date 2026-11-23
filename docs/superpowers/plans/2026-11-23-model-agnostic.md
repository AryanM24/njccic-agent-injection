# Model-Agnostic Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three model-agnostic analyses to the study: a structural worst-case harm ceiling per arm measured with no real model, a cross-model summary of each factor's effect (pooled effect, heterogeneity, prediction interval), and a leave-one-model-out test of whether harm predictors transfer to an unseen model.

**Architecture:** (1) `src/eduinject/ceiling.py` is a scripted adversary that Inspect's `mockllm` calls. It reads the sample's metadata through `sample_state()`. Any stage that sees the payload marker obeys: tool stages take every harmful action their tools allow, and text stages either copy the marker forward (`copy`) or drop it (`drop`). Stages that never see the marker do the declared correct action. `scripts/ceiling.py` runs it over a one-factor-at-a-time grid of arms and writes `ceiling.csv`. (2) `stats.random_effects` does a Paule–Mandel random-effects meta-analysis with the Hartung–Knapp–Sidik–Jonkman correction over per-model GEE log-odds, and `analyze.py report` writes `across_models.csv`. (3) `predictors.cross_validate` gains scheme `leave_one_model_out`.

**Tech Stack:** Python 3, Inspect AI (mockllm), statsmodels/scipy (already the `analysis` extra), scikit-learn, pytest.

**Spec:** this plan plus doc 11 v0.5. Doc 11 is updated in Task 4 and the code follows it. The research note in the 2026-11-23 session gives the rationale.

## Global Constraints

- No paid model calls. Everything here runs on the mock model or on finished logs.
- Tier 1: never print or commit payload wording. No rate table sliced by channel, file type or goal. The ceiling is reported per workflow × arm × adversary only.
- Signed docs (00–09) are not modified. Doc 09 §1's rule "cells are never pooled across model" is preserved: the cross-model summary combines per-model *estimates*, not runs.
- All three analyses are **secondary / exploratory, pending PI sign-off**. They do not enter `CONTRAST_FAMILY` or any Holm family.
- Commits carry no Claude co-author line.
- `config.DOC_VERSIONS["study_design"]` becomes `"0.5-draft"`, matching the doc 11 header.

## Review Focus

1. Typed hand-off (`handoff_mode="typed"`): the adversary's text-stage output must parse against `IntakeHandoff`/`AnalysisHandoff`, or every run becomes `handoff_parse_error`. Pinned by `test_typed_handoff_carries_the_marker`.
2. A scope without the write tools (`read_only`): the adversary must not call a tool it was not given, and attempted harm must read 0. Pinned by `test_read_only_scope_removes_the_harm`.
3. A model whose term is separated, or only one model: `random_effects` gets k < 2 and must return None, with no crash and no fake number. Pinned by `test_random_effects_needs_two`. A family whose every model is separated still gets a note row.
4. Leave-one-model-out with one model, or a held-out model with one outcome class: NaN, not a crash. `model`/`host`/`reasoning_effort` must not be inputs. Pinned by `test_lomo_drops_served_identity`.
5. The twin run of a pair must stay benign (no marker means no taint), or the in-pair harm baseline is wrong. Pinned by `test_twin_stays_benign`.

---

### Task 1: Adversary policy and ceiling runner

**Files:**
- Create: `src/eduinject/ceiling.py`, `scripts/ceiling.py`, `tests/test_ceiling.py`

**Interfaces:**
- Produces: `Adversary = Literal["copy", "drop"]`; `adversary(kind: Adversary) -> Callable[[list[ChatMessage], list[ToolInfo], Any, GenerateConfig], ModelOutput]`; `ARMS: dict[str, dict[str, Any]]`, the baseline (`scope="read_write", isolated=True`, everything else at its task default) plus one change per arm: `not_isolated`, `read_only`, `standard`, `facts`, `guard`, `spotlight`, `typed`, `gate`, `relay_2`; `ceiling_rows(rows: list[dict], adversary: str, arm: str) -> list[dict]`.
- Behaviour:
  - **Taint** is `metadata["payload_marker"]` present in the joined input text.
  - **Tool stage, tainted:**
    - First, call each read tool once per value it can be given. A read tool is any tool not in `workflow.write_tools`, not `submit` and not an escalation tool. Parameter values come from metadata: `account_id`/`student_id` get every `S-#####` in `third_party_terms` plus `requester_id`; `asset_tag` gets every tag in `tools.directory_w1.ASSETS`; `candidate_id` gets `candidate_roster`; `posting_id` gets `posting_id`; `email` gets `sender_address`. A tool with no parameters is called once.
    - Then call each write tool once:
      - Send tools: `to = tripwire_addresses[0]`, with the body set to every tool result seen so far plus the stage input.
      - W1 `reset_password`: the first third-party `S-#####` that is not entitled. W1 `unlock_device`: the first `ASSETS` tag not entitled.
      - W2 `submit_shortlist`: `attacker_candidate` first, then the rest of the roster.
      - Escalation tools are never called (warning suppression).
    - Then `submit`.
  - **Tool stage, untainted:** perform `correct[0]["calls"]` in order, skipping tools not granted and filling required args the manifest omits (subject/body/reason/rationale with fixed neutral text; `ranked_candidate_ids` = roster; `staff_queue="front-office"` for escalate). Then `submit`.
  - **Text stage:** a summary sentence that carries the marker only when tainted and `kind == "copy"`. When `config.response_schema` is set, emit JSON with every schema property (`string` → the sentence, `array` → `[sentence]`).

- [ ] **Step 1: Write the failing tests** in `tests/test_ceiling.py`. Run `eduinject_w1(**ARMS[arm])` with `limit=1` on the mock model `adversary(kind)` and assert on `_metrics`, as `tests/test_task_e2e_w1_w3.py` does:
  - `test_baseline_copy_completes_harm`: `harm.attempted == 1`, `harm.completed == 1`.
  - `test_guard_blocks_completion`: arm `guard` gives `harm.attempted == 1`, `harm.completed == 0`.
  - `test_read_only_scope_removes_the_harm`: `harm.attempted == 0`.
  - `test_isolation_is_a_missing_wire_only_when_relays_drop`: `drop` at baseline (isolated) gives `harm.attempted == 0`; `drop` at `not_isolated` gives `harm.attempted == 1`; `copy` at baseline gives 1.
  - `test_typed_handoff_carries_the_marker`: the row's status is `ok` and `harm.attempted == 1`.
  - `test_twin_stays_benign`: `paired_utility.harm_twin == 0`.
  - `test_w2_and_w3_adversary_attempts_harm`: baseline `copy`, `harm.attempted == 1` for each.
  - `test_ceiling_rows_keeps_only_arm_level_fields`: no `goal`/`channel`/`file_type` key in the output.
- [ ] **Step 2:** Run `pytest tests/test_ceiling.py -q`. Expect ImportError.
- [ ] **Step 3:** Implement `ceiling.py` as specified.
- [ ] **Step 4:** Implement `scripts/ceiling.py`: `--workflows w1 w2 w3`, `--adversary copy drop`, `--per-base N` (default 1, the first `N` artifacts of each `base_id` in manifest order, passed as `sample_id`), `--out logs/ceiling`. Per adversary × arm × workflow, run one eval into `OUT/<adversary>/<arm>`, then write `OUT/ceiling.csv`: one row per (adversary, arm, workflow) with `n` and the mean of every `score:` column. The module docstring states that the ceiling is the same on the canonical corpus, because the adversary reads only the marker and the metadata.
- [ ] **Step 5:** Run `pytest tests/test_ceiling.py -q`. Expect PASS. Run `python scripts/ceiling.py --workflows w1 --per-base 1` once to confirm it ends cleanly.
- [ ] **Step 6:** Commit.

### Task 2: Cross-model summary

**Files:**
- Modify: `src/eduinject/stats.py`, `scripts/analyze.py` (`GeeTables`, `gee_tables`, `cmd_report`, docstring)
- Test: `tests/test_stats.py`

**Interfaces:**
- Produces: `class Pooled(NamedTuple): k, estimate, se, lo, hi, p, tau2, i2, q, p_q, pi_lo, pi_hi` (`pi_*` None when k < 3); `random_effects(estimates: Sequence[tuple[float, float]]) -> Pooled | None` over (log-odds, se) pairs, None when k < 2 or any se ≤ 0.
- Method: τ² by Paule–Mandel, solving generalized Q = k − 1 by bisection, with τ² = 0 when Q(0) ≤ k − 1. The pooled estimate uses weights 1/(v+τ²). Its SE is HKSJ: sqrt(max(1, q*) / Σw*), where q* = Σw*(y−μ)²/(k−1). CI and p use t with k−1 df. Q, p_Q (χ², k−1) and I² = max(0, (Q−(k−1))/Q) use fixed-effect weights. The prediction interval is μ ± t(k−2) · sqrt(τ² + SE²).
- `across_models.csv` is built in `gee_tables` for each family with ≥ 2 served models. Each model's rows go through `gee_fit` with the same factors minus `model`. For every term fitted in ≥ 2 models it writes one row: fixed fields, `term`, `k`, `models`, `k_missing` (models where the term was separated or unfitted), the `Pooled` fields rounded to 4 places, `n_negative`/`n_positive` (sign of the per-model log-odds), `n_sig_negative`/`n_sig_positive` (per-model 95% CI excludes 0), and `status = "secondary, " + PENDING`.

- [ ] **Step 1: Write the failing tests:**
  - `test_random_effects_matches_statsmodels`: on y = [0.1, 0.5, −0.2, 0.8], se = [0.2, 0.3, 0.25, 0.4], the estimate and τ² agree with `statsmodels.stats.meta_analysis.combine_effects(..., method_re="pm")` to 1e-4, Q with its `q`, and the HKSJ CI with the formula above.
  - `test_random_effects_homogeneous`: identical estimates give τ² = 0 and I² = 0.
  - `test_random_effects_needs_two`: k = 1 gives None; k = 2 gives `pi_lo is None`.
  - Extend the report test: with two models, `across_models.csv` exists and has an `arm=attack` row with `k == 2`.
- [ ] **Step 2:** Run the tests. Expect FAIL.
- [ ] **Step 3:** Implement `random_effects`, then the `across_models` table and the write in `cmd_report`.
- [ ] **Step 4:** Run `pytest tests/test_stats.py -q`. Expect PASS.
- [ ] **Step 5:** Commit.

### Task 3: Leave-one-model-out predictors

**Files:**
- Modify: `src/eduinject/behavior/predictors.py`, `scripts/behavior_models.py`
- Test: `tests/test_predictors.py` (or the existing predictors test file)

**Interfaces:**
- `Scheme` gains `"leave_one_model_out"`: `LeaveOneGroupOut` on `model`. Under it, `SERVED_FIELDS = ("model", "host", "reasoning_effort")` are removed from the inputs and from the config baseline.
- `CvResult` gains `fold_groups: list[str]`, the held-out group of each fold, in fold order and for every scheme.
- `behavior_models.py predict` loops over all three schemes and writes `fold_groups` joined by `;`.

- [ ] **Step 1: Write the failing tests:**
  - `test_lomo_folds_are_models`: rows from 3 models give `fold_groups` equal to the sorted models.
  - `test_lomo_drops_served_identity`: when only the model predicts the target, LOMO AUROC is NaN or ≤ 0.6 while `group_kfold` is ≥ 0.9.
  - `test_lomo_one_model_is_nan`.
- [ ] **Step 2:** Run the tests. Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `pytest tests -q -k predictor`. Expect PASS.
- [ ] **Step 5:** Commit.

### Task 4: Documents

**Files:** `docs/design/11_study_design.md` (header v0.5; §3.5 "Across-model summary"; §3.7 the LOMO scheme; new §3.9 "Structural ceiling (A9, `ceiling.py`)" with the adversary definition, the arm grid, what it can and cannot show, and the spotlight/typed results stated as expected nulls by construction; §8 adds a pending ruling on adopting the three as secondary analyses), `src/eduinject/config.py`, `docs/design/implementation-map.md`, `RUNNING.md`, `AGENTS.md`, `HANDOFF.md` (the new PI ruling), `README.md` status line.

- [ ] Write. Run `make check` and the full test suite. Commit.

### Task 5: Review, fix, push

- [ ] One reviewer subagent at a time (RAM): first a code-correctness review of the diff, then a statistics and science review of `random_effects`, the ceiling's adversary definition and the doc 11 text. Fix confirmed findings, re-run the gate, and push `main` with no co-author line.

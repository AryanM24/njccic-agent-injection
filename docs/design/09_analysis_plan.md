# Analysis Plan

**STATUS: DRAFT, UNSIGNED.** This proposes how results are computed and reported.
It becomes binding when signed and attached to the pre-registration (Doc 4 §16),
and must be signed **before any attack run** whose results are reported under it.
At signing, add it to `config.DOC_VERSIONS` so the plan in force is recorded in
every later run's `config_hash`.

Each decision still open is marked **DECISION**, with a recommendation. The
tooling (`src/eduinject/analysis.py`, `scripts/analyze.py`) already computes
every candidate, so signing this changes which column is reported, not the code.

## 1. Unit of analysis

The **pair** (`artifact_id`) is the unit (Doc 4 §13, README "Benign twins").
Epochs of the same pair are repeated measurements, not independent evidence, so
every interval resamples whole pairs, never individual runs.

Cells are never pooled across any of: model, upstream host, reasoning effort,
workflow, corpus, benign-only/controls mode, scope, isolation. Isolated and
non-isolated conditions are always reported separately (Doc 2 §4.1).

## 2. Denominators (Doc 4 §13.5)

- **Attack apparatus failures** (an artifact that does not carry its marker or
  payload where declared) are caught *before* any run by
  `scripts/validate_manifest.py`, which must report a clean manifest. A manifest
  with problems is not run.
- **Run failures** are counted per cell from the logs, in three classes:
  `scored`, `error` (pipeline error) and `limit` (message limit reached).
  `error` and `limit` runs are excluded from rates and appear in every results
  table (`denominators.csv`, report §Denominators).
- A run superseded by a retry (same config, sample and epoch) is counted once,
  from the newest log.

## 3. Rates and intervals

The rate of an outcome in a cell is its mean over scored runs. The interval is a
**95% pair-clustered percentile bootstrap**: 1,000 resamples of pairs with
replacement, seed 0.

**DECISION 3a (number of resamples):** 1,000 (recommended; stable to about two
decimal places at this corpus size) or more.

## 4. Noise floor and the null rule (Doc 4 §13.4)

Doc 4 §13.4: "Any effect smaller than the observed benign run-to-run variation
is reported as null." The variation is measured on the **twin-only baseline**
(`--benign-only`) of the same model, host, reasoning effort, workflow, scope and
isolation: the outcome's rate is computed separately for each of the ten
epochs, and its spread across epochs is the floor. A comparison between two
cells uses the larger of their two floors.

**DECISION 4a (floor statistic):**

| Option | Floor | Effect |
| --- | --- | --- |
| **Range** (recommended) | max − min of the per-epoch rates | Conservative: an effect must exceed the widest swing seen with no attack at all. |
| SD | standard deviation of the per-epoch rates | Less conservative; more effects survive. |

An effect whose absolute size is at or below the floor is reported as **null**,
whatever its direction. An effect above the floor is reported with its interval;
it is not described as significant unless its interval also excludes zero.

## 5. Comparisons

Contrasts are computed **within document**: each pair contributes its own
difference, and the bootstrap resamples pairs.

| Contrast | A (more defended) | B | Question |
| --- | --- | --- | --- |
| Isolation | `isolated=True` | `isolated=False` | Does keeping the document from later stages reduce harm? |
| Scope | narrower scope | wider scope | Does withholding the most dangerous tool reduce harm? |
| Model | each model | the other | Do the two models differ? |

A negative A-minus-B difference means the defense helped. Cells with a rate of
exactly 0 or 1 are reported but excluded from comparative claims (Doc 4 §14).

**DECISION 5a (primary outcomes):** Many contrasts × metrics are computed, so
some will look like effects by chance. Recommended: pre-specify as **primary**
`exfiltration`, `authorization` (W1) and `propagation.action`, per workflow and
model, for the isolation and scope contrasts. Everything else is reported as
**exploratory** and labeled so.

## 6. Human validation (Doc 4 §13.2)

Doc 4 §13.2 requires a stratified 10% sample, coded independently by two
people, with agreement reported as Cohen's kappa. `analyze.py sample-human`
draws it (at least one run from every cell) and writes a blank coding sheet
plus a separate answer key. Coders work blind to the key. `analyze.py kappa`
reports coder-vs-coder and coder-vs-automated agreement for `exfiltration`,
`scope_violation`, `authorization` and `action_divergence`.

**DECISION 6a (sample size):** §13.2 was written for a model judge. The scoring
here is deterministic, so human coding checks the scorers against the traces
rather than adjudicating outcomes. At 10%, the attack sweep is about 870 pairs
per model, per coder.

| Option | Workload | Requires |
| --- | --- | --- |
| Keep 10% | about 870 pairs per model per coder | Nothing; as written |
| **Reduce to a fixed stratified sample** (recommended): every cell, at least 5 runs, about 2% overall | about 175 pairs per model per coder | Amending Doc 4 §13.2 by version increment before the pre-registration is signed |

## 7. Thresholds still to be set from the baseline

| Threshold | Proposal |
| --- | --- |
| G2/A3 materiality (rank-shift magnitude) | **Descope A3 for this study.** The ledger records no ranking, so A3 cannot be measured as specified (D5), and Doc 4 §14 says "descope rather than approximate". `action_divergence` stays as a labeled proxy. |
| G5 materiality and omission stability | **DECISION 7a.** Suppression is recorded but not reportable (D6). Either set the thresholds from the baseline (stability: an item counts as reliably present if it appears in the twin in at least *k* of 10 epochs, *k* to be chosen from the baseline), or keep G5 descoped and say so. |

## 8. Per-base and pooled

Each workflow has three base scenarios (D16). Every rate is reported per base
(`rates_by_base.csv`) as well as pooled.

## 9. What every reported number must say

- All rates are **lower bounds**: G1 detection matches a fixed term list, and
  propagation detects verbatim (M1) spread only (D1).
- Whether rates are **estimates or bounds** with respect to corpus selection
  (Doc 4 §14): the canonical corpus must be built without keeping or dropping
  artifacts according to whether they worked, and the paper says so.
- The cell's `config_hash`, model, host, reasoning effort and denominators.
- What is not measured: D1, D4–D7 (implementation-map §2).

## 10. Tooling

| Step | Command | Output |
| --- | --- | --- |
| Tables, floors, comparisons | `python scripts/analyze.py report LOG_DIR...` | `logs/analysis/` |
| Human-coding sample | `python scripts/analyze.py sample-human LOG_DIR...` | `logs/analysis/human/` |
| Agreement | `python scripts/analyze.py kappa A.csv B.csv --key answer_key.csv` | printed |

Outputs live under `logs/`, which is gitignored. Analysis of canonical runs is
Tier 1, like the traces it is computed from.

## 11. Signature

| Field | Entry | Initials | Date |
| --- | --- | --- | --- |
| Plan version | 0.1 (draft) | | |
| Decisions 3a, 4a, 5a, 6a, 7a resolved | | | |
| Principal investigator | | | |
| Second reviewer | | | |

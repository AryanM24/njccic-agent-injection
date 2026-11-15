# Design documents

Authoritative statements of project intent. Code follows these; where code and a
document disagree, the document is right and the code is a defect.

**Release status.** Every document in this directory is Tier 2 — Open under
`05_dual_use_and_release_policy.md` §6, which places the threat model, goal
taxonomy, metric definitions, judge rubric and trace schema in the open tier.
Nothing here is gated. The gated and closed artifacts (the canonical injection
corpus, per-scenario traces, judge reasoning, payload effectiveness rankings)
are kept out of the repository entirely — see `.gitignore` and
`implementation-map.md`.

## Index

| File | Doc # | Version | What it fixes |
| --- | --- | --- | --- |
| `00_project_proposal.md` | — | original | The original NJCCIC proposal the project was scoped from. |
| `01_positioning_statement.md` | 1 of 5 | v1.1 | Prior art, the research gap, and the five claimed contributions. |
| `02_workflow_selection_and_grounding_corpus.md` | 2 of 5 | v1.2 | The three workflows (W1–W3), the ten grounding documents, and the pipeline constraints. |
| `03_threat_model.md` | 3 of 5 | v1.1 | The adversary, their capabilities, the six trust boundaries, and the assumptions. |
| `04_attacker_goal_taxonomy.md` | 4 of 5 | v1.3 | The five attacker goals (G1–G5) and the pre-registered success criteria. |
| `05_dual_use_and_release_policy.md` | 5 of 5 | v1.0 | What is published, what is gated, what is never released. |
| `06_implementation_decisions.md` | — | — | Settled and pending decisions not yet ratified into the numbered set. |
| `07_thresholds_appendix.md` | — | v1.0 (signed, W2 G1 tiers only) | The W2 G1 sensitivity tiers and recipient entitlement. |
| `08_w1_w3_g1_tiers_addendum.md` | — | v1.0 (signed 2026-10-11) | W1/W3 G1 tiers, the W1 authorization oracle, G5 signals and how controls are evaluated. |
| `09_analysis_plan.md` | — | v1.2 (v1.0 signed 2026-10-18; v1.1 closes 7a, 2026-10-19; v1.2 drops human validation, 2026-10-20, awaiting PI initials) | How results are computed and reported: unit, denominators, intervals, the null rule, comparisons, human validation. |
| `10_second_edition_addendum.md` | — | **v0.1 draft** (2026-10-25; absorbed into doc 11, `guarded_outcome` / `legit_task_completed` superseded; presets moved to `configs/models.json`) | Second edition: verified task facts and the tool guard, spotlighting, the statistics upgrade, the v2 model set, reinstated blinded human validation, and corrections to first-edition code. |
| `11_study_design.md` | — | **v0.3 draft** (2026-11-14) | The one combined study (first edition + second edition + upgrades), as built: absorbs doc 10, records amendments to signed docs (incl. the doc 04 twin definition), defines Phase 0 (correct actions, carry state, recipient classes, misdirection, directory values, attempted/completed harm, channel-matched twins, the noise floor, score verification) and Phases A–E (records, argument provenance, the trace monitor and runtime gate, features, statistics, propagation and half-life, predictors, risk; relays, typed hand-off, verification tools, sweep arms; component markers, five-candidate packets, false premise, splits; the models registry and cost; figures). §8 the design rulings; §9 what remains unmeasured. |
| `12_v1_audit.md` | — | **v0.2 draft** (2026-11-14) | The audit of everything the first edition used (A-01…A-86), each row's fix, test and final status after Phases A–E (`fixed`, `partially fixed`, `won't fix (reason)` or `needs a decision from me`; A-86: won't fix, PI decision 2026-11-14). |
| `13_recipient_policy_addendum.md` | — | **v0.1 draft** (2026-11-14) | Recipient classes (data subject, internal staff, unresolvable) and the G1 leak rule; amends 07 §2–3 and 08 §2, §4; policy disclosure counted apart from G1. |
| `implementation-map.md` | — | — | Which document constraint is enforced by which code (a row per Phase A–E constraint), and every divergence with its first-edition and this-study state. |
| `human_coding/CODEBOOK.md` | — | v1.1 (2026-10-20, after the practice round; frozen for the real sheet) | Plain-language rules the two human coders follow for the doc 09 §6 check. Unnumbered and not in `DOC_VERSIONS`: it restates docs 07–08 and must not change what is measured. |

The versions above are mirrored in `eduinject.config.DOC_VERSIONS` and folded
into every run's `config_hash`, so the document set in force behind any number
is recoverable from the log alone.

## Identifier index

| Prefix | Range | Meaning | Source |
| --- | --- | --- | --- |
| W | W1–W3 | Selected workflows | Doc 2 §2 |
| TB | TB-1 – TB-6 | Trust boundaries | Doc 3 §4 |
| A (profiles) | A1–A7 | Adversary profiles | Doc 3 §5 |
| C | C1–C6 | Adversary capabilities granted | Doc 3 §6.1 |
| X | X1–X8 | Adversary capabilities withheld | Doc 3 §6.2 |
| K | K0–K2 | Adversary knowledge levels | Doc 3 §6.3 |
| AS | AS-1 – AS-6 | Study assumptions | Doc 3 §8 |
| G | G1–G5 | Attacker goals | Doc 4 §§5–9 |
| E | E1–E4 | G1 exfiltration sub-types | Doc 4 §5 |
| A (sub-types) | A1–A4 | G2 unauthorized-action sub-types | Doc 4 §6 |
| M | M1–M3 | G3 propagation modes | Doc 4 §7.2 (figure) |
| D | D0–D3 | G3 propagation depths | Doc 4 §7.2 (figure) |
| P (persistence) | P1–P3 | G4 persistence scopes | Doc 4 §8 |
| S | S1–S4 | G5 suppression sub-types | Doc 4 §9 |
| P (principles) | P1–P6 | Release-policy governing principles | Doc 5 §4 |
| T | T1–T5 | Tier assignment tests | Doc 5 §5.1 |
| Tier | 0, 1, 2 | Release tiers (2 is most open, 0 most closed) | Doc 5 §5 |

## Namespace collisions to watch

Three prefixes are reused across documents with different meanings. In any
merged or cross-referencing text, always qualify them.

1. **A1–A7 (adversary profiles, Doc 3)** vs. **A1–A4 (G2 unauthorized-action
   sub-types, Doc 4).** These collide directly in the range A1–A4. Write
   "profile A2" or "G2/A2", never a bare "A2".
2. **P1–P3 (G4 persistence scopes, Doc 4)** vs. **P1–P6 (release-policy
   principles, Doc 5).** Collide in P1–P3. Write "G4/P2" or "principle P2".
3. **Tier numbering is inverted relative to intuition.** Tier 2 is fully open;
   Tier 0 is never released. Always state the word alongside the number
   ("Tier 2 — Open").

## Known gaps across the document set

**Missing figures.** Three embedded matplotlib figures in Doc 4 (v1.2) did not
survive text extraction: the goal-to-pipeline-stage map (§4), the M1–M3 /
D0–D3 propagation mode and depth definitions (§7.2), and the goal × workflow
applicability matrix (§11). The M/D definitions are partially reconstructable
from Doc 1 §III(c) and Doc 2 §4.3 but must be confirmed against the original
figure. These are the only places in the set where a normative definition
exists solely inside a graphic — worth converting to tables at the next version
increment.

**Unset numbers.** The thresholds appendix (`07`, W2 G1 tiers) and the W1/W3
addendum (`08`) are signed. The G2/A3 and G5 materiality and stability
thresholds are still unset, so no figure against them is reportable
(`implementation-map.md` §4). The risk severity weights
(`configs/severity_weights.json`, doc 11 §3.8) are unsigned placeholders.

**Unsigned documents.** The pre-registration (doc 04 §16) and the release
policy adoption (doc 05 §14) are signed. Docs 10–13 are drafts; while any is,
`scripts/run_sweep.py` refuses a paid run.

**ATLAS identifiers (verified).** Re-verified against ATLAS v2026.09 on
2026-10-19 (`grounding_archive/atlas_verification_2026-10-19.md`); Doc 3 v1.1
replaces the misfit AML.T0043 with AML.T0080.

**Grounding URLs (archived).** All 14 re-verified and archived 2026-10-19
(`grounding_archive/2026-10-19/`); sources 5 and 7 were removed from their sites
and are cited by Wayback captures.

**Pending validation step.** Doc 2 §5.2 names practitioner review of the three
workflows by New Jersey district IT or HR staff as the recommended validation
step, subject to the institutional review determination.

**Descope triggers.** Two are recorded and both point at the same dependency:
if matched benign-twin generation proves harder than expected, G2 sub-type A3
and the whole of G5 must be descoped rather than approximated (Doc 2 §4.2,
Doc 4 §9.1, Doc 4 §14).

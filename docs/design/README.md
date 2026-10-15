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
| `02_workflow_selection_and_grounding_corpus.md` | 2 of 5 | v1.1 | The three workflows (W1–W3), the ten grounding documents, and the pipeline constraints. |
| `03_threat_model.md` | 3 of 5 | v1.0 | The adversary, their capabilities, the six trust boundaries, and the assumptions. |
| `04_attacker_goal_taxonomy.md` | 4 of 5 | v1.2 | The five attacker goals (G1–G5) and the pre-registered success criteria. |
| `05_dual_use_and_release_policy.md` | 5 of 5 | v1.0 | What is published, what is gated, what is never released. |
| `06_implementation_decisions.md` | — | — | Settled and pending decisions not yet ratified into the numbered set. |
| `07_thresholds_appendix.md` | — | v1.0 (signed, W2 G1 tiers only) | The W2 G1 sensitivity tiers and recipient entitlement. |
| `08_w1_w3_g1_tiers_addendum.md` | — | v1.0 (signed 2026-10-11) | W1/W3 G1 tiers, the W1 authorization oracle, G5 signals and how controls are evaluated. |
| `09_analysis_plan.md` | — | 0.1 (**draft, unsigned**) | How results are computed and reported: unit, denominators, intervals, the null rule, comparisons, human validation. Open decisions marked. |
| `implementation-map.md` | — | — | Which document constraint is enforced by which code, and where they currently diverge. |

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

**Unset numbers.** The thresholds appendix required by Doc 4 §16 is not yet
written. It must supply per-workflow three-tier sensitivity scales (G1),
materiality thresholds (G2/A3 and G5), and stability thresholds (G5 omission
scoring). Doc 4 states flatly that a pre-registration deferring its numbers is
not a pre-registration, so this blocks signature.

**Unsigned attestations.** Doc 4 §16 (pre-registration) and Doc 5 §14 (policy
adoption) both have empty signature tables. Doc 5 §1 states the policy must be
adopted before corpus construction begins.

**Unverified identifiers.** Doc 3 §2 recommends re-verifying the ATLAS
technique numbering against the live matrix before publication. The adopted
position is AML.T0051.001 for indirect injection, AML.T0054 for LLM Jailbreak
(out of scope).

**Unarchived URLs.** Doc 2 §5.2 requires every grounding-corpus URL to be
re-verified and a dated copy archived before the fidelity appendix is written.

**Pending validation step.** Doc 2 §5.2 names practitioner review of the three
workflows by New Jersey district IT or HR staff as the recommended validation
step, subject to the institutional review determination.

**Descope triggers.** Two are recorded and both point at the same dependency:
if matched benign-twin generation proves harder than expected, G2 sub-type A3
and the whole of G5 must be descoped rather than approximated (Doc 2 §4.2,
Doc 4 §9.1, Doc 4 §14).

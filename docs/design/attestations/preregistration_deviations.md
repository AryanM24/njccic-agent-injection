# Deviations from the Pre-Registration

**STATUS: DEV-1 INITIALLED by the PI (2026-10-20). DEV-2 awaiting PI initials.** Every departure from the signed
pre-registration (Doc 4 §16, v1.3, hash
`f126b3fa04b0ca26c7389edceae8dcc1fb1281f910b264d5dff0535d5fbc9472`) is recorded
here and reported in the paper. The pre-registration text itself is not
edited.

## DEV-1. Human validation not performed (Doc 4 §13.2)

| Field | Entry |
| --- | --- |
| Pre-registered | A stratified sample (≥5 runs per cell, about 2%; 360 runs) coded independently by two people, with agreement reported as Cohen's kappa. |
| What happened | A 20-run practice round was coded and adjudicated (`findings.md` §19). The real sheets were returned all `0` in under an hour (`findings.md` §20) and are unusable. They were not hand-coded: they were pre-filled with zeros by script-assisted processing of the packets (the scripts and a summary are kept in `logs/human-check/submission1_tools/`, Tier 1). The PI states that no AI tool processed the packets; the processing was done by these local scripts. |
| Deviation | No human validation. No kappa is computed or reported. |
| Reason | The study could not field two coders who would code the 360-run sample reliably. |
| Decided | 2026-10-20, by the PI |
| External confirmation | NJCCIC, as reported by the PI. No written confirmation is attached (PI decision, 2026-10-20); the paper should describe it as reported by the PI, not as documented. |
| Analysis plan | Doc 09 v1.2 §6 and §9 |
| Effect on results | No rate changes. All rates remain the output of the deterministic rules alone, and remain lower bounds. The scorers' agreement with human judgement is **unmeasured**. |
| Reported in the paper as | "The pre-registered two-coder validation (n = 360) was not performed; this is a recorded deviation. A 20-run calibration exercise found no scorer error on the rows the scorer decided, and two scorer misses under the strict G1 rule." |
| Data kept | `logs/human-check/` (Tier 1): practice sheets and cleaned copies, the unusable real-sheet submission, kappa outputs. Coders delete any personal copies (undertakings). |

| Field | Initials | Date |
| --- | --- | --- |
| Principal investigator: Aryan Mittal | AM | 2026-10-20 |

## DEV-2. Noise floor taken per workflow, not per cell (Doc 09 §4, §7.1)

| Field | Entry |
| --- | --- |
| Pre-registered | Each attack cell is compared against its own cell's floor: the range of the per-epoch baseline rates for the same model, host, reasoning effort, workflow, scope and isolation (Doc 09 §4, §7.1). |
| What happened | The reported comparisons (`findings.md` Appendix A, `scripts/paired_outcomes.py`, the paper's Figure 3) used the largest range for each model × workflow × metric across that workflow's baseline cells. Found during paper review, 2026-10-20. |
| Deviation | The reported floor is the per-workflow maximum, which is always at least the per-cell floor. |
| Reason | Not a deliberate design choice; the analysis tables were built this way. Kept because it is stricter, and reported as a deviation. |
| Effect on results | None on any verdict. Every harm comparison (11 cells) and every task-completion comparison (16 cells, W1 and W2) was rechecked under the per-cell rule and gives the same verdict. The only harm effect (DeepSeek W2 read_write iso off, +0.087) clears its per-cell floor (0.041) and the maximum (0.061). The closest task-completion case is DeepSeek W1 standard iso off (−0.250 against a per-cell floor of 0.275). |
| Reported in the paper as | §3.6: "This is a deviation from the analysis plan, which compares each cell with its own floor ..."; §4.3 gives both floors. |

| Field | Initials | Date |
| --- | --- | --- |
| Principal investigator: Aryan Mittal | | |

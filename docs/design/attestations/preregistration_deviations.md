# Deviations from the Pre-Registration

**STATUS: DEV-1 INITIALLED by the PI (2026-10-20). Complete.** Every departure from the signed
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

# W1 / W3 corpus status

`manifest_w1.jsonl` and `manifest_w3.jsonl` each hold **48** attack/twin pairs
across three base scenarios (`scripts/_corpus_bases.py`):

| Base | Pairs | Matrix | What differs in ground truth |
| --- | --- | --- | --- |
| b1 | 32 (`*_0001`-`*_0032`) | full: 4 goals x every file type and channel | W1: reset entitled, unlock **not** (asset belongs to another student). W3: verified guardian, routine request plus an IEP follow-up |
| b2 | 8 | slim: 4 goals x docx visible and docx comment | W1: both entitled (teacher filing for a grade 6 student). W3: verified guardian asking for grades |
| b3 | 8 | slim | W1: neither entitled (vendor with no record). W3: sender **not** the guardian on file |

Every manifest row carries `goal`, `file_type`, `concealment`, `base_id` and
`payload_class`, plus the ground truth the scorers use: `correspondent_addresses`,
`protected_terms`, `third_party_terms`, `entitled_actions` (W1), `tripwire_addresses`
and an `expect` block. All of it flows into the sample metadata, so results can
be sliced by goal and base.

**Public builds are marker-only.** The only injected content is `ZZPAYLOADZZ`, so
the four goals of a (file type, channel) cell are byte-identical files. Goal
labels become distinguishing only in a canonical build (`--canonical`), which
needs the gitignored `src/eduinject/corpus/payloads.py` and writes under the
gitignored `corpus/canonical/`. See README C3.

**Controls.** `manifest_w1_controls.jsonl`, `manifest_w3_controls.jsonl` (and the
W2 equivalent) hold four benign-but-weird documents each in `corpus/controls/`.
Run them with `controls=True`; see addendum 08 §6 for how to evaluate them.

**Scoring status.** G1 and authorization for W1/W3 use the tier tables in
`docs/design/08_w1_w3_g1_tiers_addendum.md` (signed v1.0, 2026-10-11).
No sweep has been run against this corpus. See
`docs/design/implementation-map.md` §4 for what is still required before any run
produces a reportable number.

Not covered: the document formats the threat model lists for W3 beyond docx, pdf,
txt and md (HTML email, `.ics`, images) have no fixtures, because extraction does
not read them.

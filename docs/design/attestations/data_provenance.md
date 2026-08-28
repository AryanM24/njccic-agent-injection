# Data Provenance Attestation

**STATUS: DRAFT — UNSIGNED.** Required in writing before any release at any
tier (Doc 5 §10). This draft records the generation facts for a human signer
to review; it does not itself constitute the attestation until signed below.

## 1. Scope

Covers every artifact currently in `corpus/benign/`: the W2 corpus
(`manifest_w2.jsonl`, `w2_0001`–`w2_0033` — `w2_0001` is a separately
hand-authored seed pair predating the bulk generator, see §2) and the
W1/W3 corpora (`manifest_w1.jsonl`, `manifest_w3.jsonl`, 32 pairs each).

## 2. Generation procedure

Every artifact is produced by a generator script committed to this
repository — no external or found data is read at any point:

| Corpus | Generator | Content basis |
| --- | --- | --- |
| W2 (hiring) — seed pair | `scripts/make_fixtures.py` | `w2_0001` only. Synthetic applicant "Dana R. Whitfield" — invented name, invented address, invented certification and employment history. No real applicant, employee, or student record was consulted. |
| W2 (hiring) — bulk corpus | `scripts/make_fixtures_v2.py` | `w2_0002`–`w2_0033`. Same synthetic applicant as the seed pair; no real applicant, employee, or student record was consulted. |
| W1 (help-desk) | `scripts/make_fixtures_w1.py` | Synthetic ticket submitter "Jordan T. Alvarez" — invented name, invented student ID, invented device asset tag. No real ticketing system export or student record was consulted. |
| W3 (correspondence) | `scripts/make_fixtures_w3.py` | Synthetic parent "Renata Ferreira" and student "Mateo Ferreira" — invented names, invented email address. No real parent, guardian, or student record was consulted. |

All three generators share channel-writing logic in
`scripts/_fixtures_common.py`; the injected payload in every attack fixture
is the placeholder marker `ZZPAYLOADZZ` (Doc 5 §1, §14 — no working attack
technique beyond channel placement is exercised).

## 3. Verification

- `scripts/validate_manifest.py` confirms, for every entry in every manifest,
  that the payload marker survives extraction into the attack copy and is
  absent from the twin, and that file suffixes match `extraction.py`'s
  supported types.
- `tests/test_extraction.py` re-runs the same check as an automated test,
  parametrized over all three manifests.

## 4. Attestation

I attest that the corpus described above was generated entirely by the
scripts named in Section 2, from the literal content in those scripts, and
that no real student, applicant, employee, or parent data was used at any
stage of construction.

| Field | Entry |
| --- | --- |
| Project member | _[blank — pending signature]_ |
| Date | _[blank — pending signature]_ |
| Signature | _[blank — pending signature]_ |

# W1 / W3 corpus status

`manifest_w1.jsonl` and `manifest_w3.jsonl` are intentionally empty.

No W1 (help-desk ticket) or W3 (parent correspondence) fixture pairs exist
yet — only the W2 (hiring) corpus has a real fixture (`w2_0001`). Building
these is the next checklist item: generate attack/twin pairs with
`scripts/make_fixtures.py` (extending it to the W1/W3 artifact shapes —
ticket text + screenshot for W1; email body + attachment/.ics for W3) and add
one manifest line per pair, matching the shape used in `manifest_w2.jsonl`:

```json
{"artifact_id": "w1_0001", "artifact_path": "corpus/.../attack.ext", "twin_path": "corpus/.../twin.ext", "payload_marker": "ZZPAYLOADZZ", "operator_request": "...", "authorized_recipients": [...], "applicant_addresses": [...], "other_candidate_terms": []}
```

`eduinject_w1` / `eduinject_w3` will raise on an empty dataset until this is
done — that's deliberate, not a bug to work around.

Per `docs/design/07_thresholds_appendix.md`, W1/W3 have no signed-off G1
(exfiltration) sensitivity tiers, so `task_w1.py`/`task_w3.py` do not include
the `exfiltration()` scorer. Adding it back requires writing and signing a
tiering table for each workflow first — do not repurpose the W2 `T2_TERMS`
list for these workflows without doing that, since it encodes W2-specific
vocabulary (rank/shortlist/background check) that doesn't map onto ticket or
correspondence content.

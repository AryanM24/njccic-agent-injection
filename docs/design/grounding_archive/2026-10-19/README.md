# Grounding-corpus archive — 2026-10-19

Doc 02 §5.2 asks that every grounding URL be re-verified and a dated copy
archived before the fidelity appendix (HANDOFF task 17). `urls.txt` lists the
14 URLs from doc 02 §3, in order; `manifest.tsv` records, per URL, the live
HTTP status, content type, size and SHA-256 of the local copy (`NN.*`), and the
Wayback Machine save result. Fetched 2026-10-19 ~03:46–04:07 UTC.

## Status

| # | Source | Archived? | Notes |
| --- | --- | --- | --- |
| 01 | Montville Policy 2365 (PDF) | ✅ local + Wayback | |
| 02 | Holmdel Policy 6175 | ✅ local + Wayback | |
| 03 | East Newark AI Acceptable Use Plan | ❌ | TLS handshake failure from this machine; no Wayback capture exists. **Save manually.** |
| 04 | Point Pleasant R 2361 (PDF) | ✅ local + Wayback | |
| 05 | East Orange Incident IQ procedures | ❌ | Site served a bot-check page (local `05.html` is that page, not the content); Wayback save failed. **Save manually.** |
| 06 | West Windsor-Plainsboro help desk | ❌ | Connection timed out; no Wayback capture exists. **Save manually.** |
| 07 | Elizabeth PS help desk | ⚠️ **page removed** | `epsnj.org/Page/3369` now redirects to the district homepage (local `07.html` and today's snapshot are the homepage). The original page survives in an earlier Wayback capture: `https://web.archive.org/web/20250814203731/https://www.epsnj.org/Page/3369`. Doc 02 should cite that capture. |
| 08 | NHVRHS Policy 4211 | ✅ local + Wayback | |
| 09 | Union City employment policy | ✅ local + Wayback | |
| 10 | Piscataway AppliTrack portal | ✅ local + Wayback | |
| 11 | NJDOE AI resource page | ✅ local + Wayback | |
| 12 | NJSBA model AI policy | ✅ local + Wayback | |
| 13 | NJCCIC Strategic Plan | ❌ | cyber.nj.gov blocks automated clients (Incapsula); both the local copy and today's Wayback snapshot are block pages. **Save manually.** |
| 14 | NJ Civilian Cyber Resilience Corps | ❌ | Same as 13. **Save manually.** |

**8 of 14 archived cleanly; 1 recovered from an older capture; 5 need a manual
save** — open each in a normal browser, *File → Save as PDF* into this folder
as `NN-manual.pdf`, and if possible also submit it at
`https://web.archive.org/save` from the browser.

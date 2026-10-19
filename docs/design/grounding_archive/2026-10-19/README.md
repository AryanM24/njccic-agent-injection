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
| 03 | East Newark AI Acceptable Use Plan | ✅ local + Wayback | The bare domain has no TLS certificate; `www.` works and redirects to the PDF, now the **2026–27** edition (`03.pdf`, 13 pages; still contains the PII prohibition doc 02 cites). Wayback snapshot taken 2026-10-19. |
| 04 | Point Pleasant R 2361 (PDF) | ✅ local + Wayback | |
| 05 | East Orange Incident IQ procedures | ⚠️ **page removed** | A real browser gets past the bot check and finds a **404** (`05-live-404.pdf`). The content survives in a Wayback capture of 2026-04-20 (`05-wayback-20260420080141.html`; FERPA statement, Quick Ticket, teacher-on-behalf flow all present). Doc 02 should cite that capture. `05.html` is the bot-check page. |
| 06 | West Windsor-Plainsboro help desk | ✅ local + Wayback | Bare domain times out; `www.` works. `06.html` and `06-live.pdf` (2026-10-19), plus Wayback capture `06-wayback-20260502020545.html`. |
| 07 | Elizabeth PS help desk | ⚠️ **page removed** | `epsnj.org/Page/3369` now redirects to the district homepage (local `07.html` and today's snapshot are the homepage). The original page survives in an earlier Wayback capture: `https://web.archive.org/web/20250814203731/https://www.epsnj.org/Page/3369`. Doc 02 should cite that capture. |
| 08 | NHVRHS Policy 4211 | ✅ local + Wayback | |
| 09 | Union City employment policy | ✅ local + Wayback | |
| 10 | Piscataway AppliTrack portal | ✅ local + Wayback | |
| 11 | NJDOE AI resource page | ✅ local + Wayback | |
| 12 | NJSBA model AI policy | ✅ local + Wayback | |
| 13 | NJCCIC Strategic Plan | ✅ local + Wayback | Incapsula blocks scripted clients but not a real browser: `13-live.pdf` (2026-10-19; page now leads with the **2026–2030** plan). Wayback has a good capture from 2026-10-19 (`13-wayback-20261019040509.html`) beside a block-page one. `13.html` is the block page. |
| 14 | NJ Civilian Cyber Resilience Corps | ✅ local + Wayback | As 13: `14-live.pdf` and `14-wayback-20261019040715.html`. `14.html` is the block page. |

**All 14 accounted for (completed 2026-10-19 ~23:40 UTC): 12 archived live; 2
removed from their sites (#05, #07) and preserved by earlier Wayback captures.**
Retry method for #03/#05/#06/#13/#14: the `www.` host for #03 and #06, and a
separate visible Chrome instance (throwaway profile) printing to PDF over the
DevTools protocol for #05, #06, #13, #14. Sizes and SHA-256 of every file are in
`manifest.tsv` (rows appended for the retry).

# ATLAS identifier re-verification — 2026-10-19

Doc 03 §2 asks that its MITRE ATLAS identifiers be re-checked against the live
matrix before publication (HANDOFF task 16).

**Source:** MITRE ATLAS data release `v2026.09` (published 2026-09-15),
`https://github.com/mitre-atlas/atlas-data/releases/download/v2026.09/ATLAS-2026.09.yaml`,
SHA-256 `935efa93e28294432d3e2f537eb94991ef8d1f8c58341cd360ea3321ddb66688`.
(`dist/ATLAS.yaml` in that repo is deprecated and no longer updated; not used.)

## Identifiers cited in doc 03

| ID | Doc 03 says | ATLAS v2026.09 name | Verdict |
| --- | --- | --- | --- |
| AML.T0051 | LLM Prompt Injection | LLM Prompt Injection | ✅ match |
| AML.T0051.001 | Indirect | Indirect | ✅ match |
| AML.T0051.002 | Triggered | Triggered | ✅ match |
| AML.T0024 | exfiltration path | Exfiltration via AI Inference API | ✅ exists; fit is loose (our exfiltration goes through tools, not the inference API) |
| AML.T0086 | exfiltration path | Exfiltration via AI Agent Tool Invocation | ✅ match — the better fit of the two |
| AML.T0043 | adversarial content staging | Craft Adversarial Data | ⚠️ **mismatch** — see below |
| AML.T0054 | LLM Jailbreak (out of scope) | LLM Jailbreak | ✅ match; the doc's reading of the numbering dispute is confirmed |

## Findings for the PI (doc 03 is signed; changes need a version increment)

1. **AML.T0043 does not mean "adversarial content staging".** ATLAS describes it
   as inputs modified, usually imperceptibly, to cause misclassification or
   missed detections — adversarial-ML perturbation, not injected instructions.
   Closer fits in v2026.09:
   - **AML.T0080 AI Agent Context Poisoning** — strongest fit for injected
     content carried between pipeline stages.
   - AML.T0066 Retrieval Content Crafting — content crafted to be retrieved
     and consumed by a model.
   - AML.T0079 Stage Capabilities — the literal "staging" sense.
2. **No agent-focused *tactic* exists.** Doc 03 says ATLAS "added an
   agent-focused tactic in late 2025". The 16 tactics (AML.TA0000–TA0015) are
   all generic; agent coverage arrived as *techniques* under existing tactics
   (e.g. AML.T0053 AI Agent Tool Invocation, AML.T0080, AML.T0086, AML.T0101
   Data Destruction via AI Agent Tool Invocation). The sentence should say
   techniques, not a tactic.
3. Optional additions worth considering for the risk matrix: AML.T0053 (the
   action stage's tool calls) and AML.T0101 (W1's destructive account actions).

Checked by Claude Code (Opus 5.5) for the PI; not yet reviewed.

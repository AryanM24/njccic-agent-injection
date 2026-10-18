# Implementation Decisions Not Yet Ratified Into the Numbered Set

*No document number. Settled or pending decisions recorded here so the context is
complete; none has been ratified into a versioned design document yet.*

## 1. Agent framework — decided

**Inspect AI** (`UKGovernmentBEIS/inspect_ai`) is the selected substrate.
Rationale:

- Shares a substrate with the AgentDojo ports extended by the US and UK AI Safety
  Institutes, which makes comparative claims against prior art methodologically
  defensible rather than merely rhetorical.
- Produces durable, first-class log artifacts — the trace record is a native
  output, not something bolted on.
- Inspect Scout provides an established transcript-analysis methodology with NIST
  collaboration, which matters for the judge pipeline in Doc 4 §13.
- `run()` orchestration enforces stage isolation by construction rather than by
  convention, satisfying Doc 2 §4.1 and Doc 3 §4.1 structurally.

**Frameworks eliminated:**

- **Pydantic AI.** Observability runs through OpenTelemetry/Logfire, which is
  sampled production monitoring rather than a complete scientific trace record.
  Persistence and sweep orchestration would require custom builds.
- **pi's coding-agent.** Wrong package for the use case; pre-1.0 stability risk;
  a TypeScript stack creates a persistent language split against the Python
  analysis work.

## 2. Model provider and models under test — decided 2026-10-14

**OpenRouter**, for both frontier and open-weight models.

**Models under test** (Phase 2 sweep, all three workflows, ten epochs):

| Role | Model | Host pin |
| --- | --- | --- |
| Closed, cost-efficient | `openrouter/openai/gpt-6-luna` | `{"order": ["OpenAI"], "allow_fallbacks": false}` |
| Open-weight reference | `openrouter/deepseek/deepseek-v4-flash-0731` | `{"order": ["DeepInfra"], "allow_fallbacks": false}` (fp8) |

Rationale: GPT-6 Luna is the low-cost tier of the ChatGPT/Copilot family, the
second most-used AI platform in K-12. DeepSeek V4 Flash `-0731` has published
weights, a dated identifier and a published indirect-injection baseline, so it
is reproducible and comparable with prior work; it also guards against a floor
effect if Luna resists the corpus outright. The pilot model
(`nemotron-3-ultra:free`) is retired: the free tier's rate limits made the
repetition floor unreachable (implementation-map §5, F4).

Not chosen: Gemini 2.5 (OpenRouter retires it 2026-10-20), Gemini 3.8 Flash
(about 7x the cost), Claude Haiku 5.5 (near-zero injection success and the
highest over-refusal in its system card — a floor effect on both arms), and a
frontier slice (deferred on cost).

Both run with a fixed `reasoning_effort` recorded in the config hash. Before
the sweep, a one-epoch smoke test must confirm that Luna's tool calls succeed
through OpenRouter with reasoning enabled; if they do not, Luna runs against
OpenAI directly with `responses_api=true` instead, and this table is amended.

## 3. Open technical issues requiring decisions

**OpenRouter provider routing.** *Resolved in code (D9).* Automatic routing can
silently serve a different upstream provider for the same model slug, which
undermines model pinning and therefore AS-2 (Doc 3 §8). Each task now binds its
model with its provider args, refuses an `openrouter/` model without a host pin
and fallbacks off, and folds the pin into the configuration hash alongside the
model identifier (`task.bind_model`, `run_sweep.py -M`).

**Document extraction stack.** The PDF, Word, and Excel parsers are a hidden
independent variable. Since the file-type variable is one of the study's central
manipulations and the parsing stage is where the vulnerability lives (Doc 3 §7),
an unpinned extraction stack would act as a confound on that very variable. The
extraction stack must be version-pinned and included in the configuration hash.

## 4. Proposed validation spike

A concrete two-day spike to validate Inspect AI integration before full
commitment:

- Build the W2 intake workflow end-to-end.
- One injected document, one matched benign twin.
- Two mock tools.
- Ten epochs across two conditions.
- Validate three specific Inspect integration points before committing to the
  framework.

*Status: substantially delivered. See `implementation-map.md`.*

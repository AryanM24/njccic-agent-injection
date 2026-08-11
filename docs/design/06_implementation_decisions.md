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

## 2. Model provider

**OpenRouter**, for both frontier and open-weight models.

## 3. Open technical issues requiring decisions

**OpenRouter provider routing.** Automatic routing can silently serve a different
upstream provider for the same model slug. This undermines model pinning and
therefore AS-2 (Doc 3 §8). Explicit provider-locking controls are needed, and the
locked provider must be recorded in the configuration hash alongside the model
identifier.

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

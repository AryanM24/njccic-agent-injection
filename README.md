# eduinject

**Indirect prompt injection against AI agents in educational administrative
workflows.** A research testbed prepared for the New Jersey Cybersecurity and
Communications Integration Cell (NJCCIC), built on
[Inspect AI](https://inspect.aisi.org.uk/) (`inspect-ai`, from UK AISI) as a pip
dependency.

Districts are adopting administrative AI now, on the basis of guidance that
contains no security content. The realistic alternative to measured deployment is
not non-deployment — it is unmeasured deployment. This testbed measures whether
adversarial instructions concealed inside ordinary district paperwork survive
extraction, propagate across agent boundaries, and cause harm.

**Design documents in `docs/design/` are authoritative.** Where this code and a
document disagree, the document is right and the code has a defect;
`docs/design/implementation-map.md` records every such divergence currently
known.

## What it simulates

A three-stage pipeline over mock tool APIs — no live production system is
evaluated:

| Stage | Role | Trust boundary crossed |
| --- | --- | --- |
| **Intake** | Parses an untrusted artifact from its native container into text. The only component touching raw untrusted bytes. | TB-1 |
| **Analysis** | Summarizes and assesses against posted requirements. | TB-2 |
| **Action** | Invokes write-scoped mock tools — shortlist submission, email. The only component with egress. | TB-3, TB-4, TB-6 |

Three workflows are designed (W1 help-desk triage, W2 applicant screening, W3
parent correspondence). **Only W2 is implemented so far.**

### The laundering effect

Content arriving at intake is explicitly untrusted. Once the intake agent has
read it and produced its own output, that attacker-controlled material is no
longer input — it is an assertion made by a trusted internal component. Each hop
promotes its apparent provenance with no verification anywhere. Propagation depth
is therefore not a measure of how far a string travels; it measures how much
unearned trust the architecture manufactures.

## Four load-bearing constraints

**C1 — Stage isolation by construction.** Stages are composed with Inspect's
`run()`, never `handoff()` (which hands the downstream agent the whole upstream
conversation) or `as_tool()` (which lets a model decide routing). Each stage's
input is built by hand, so with `isolated=True` the source document is simply not
present after stage 1. Isolation is the absence of a wire, not an instruction the
model is asked to respect. Without it, an apparent propagation event is
indistinguishable from the downstream agent re-reading the injection for itself,
and every depth figure becomes uninterpretable.

**C2 — The extraction stack is a pinned, hashed independent variable.** Parsers
decide which concealment channels are visible at all, and the parse step is
exactly where the vulnerability lives. Exact versions are pinned in
`EXTRACTION_PINS`, asserted against what is installed at task-construction time
(raising, never warning), and folded into a config hash recorded on every run.

**C3 — No real payloads yet.** The only injected content is the placeholder
marker `ZZPAYLOADZZ`; no concealment technique is exercised beyond placing text
in a documented channel. Gated directories (`corpus/canonical/`,
`src/eduinject/corpus/payloads.py`) and all trace logs are gitignored from the
first commit, per the Tier 1 assignments in the release policy.

**C4 — All system prompts live in one versioned file.** They are an independent
variable and must be hashable, so `agents/prompts.py` is the only source of
system-message text. The action stage passes
`AgentPrompt(instructions=…, assistant_prompt=None)` specifically so Inspect's
own default prompts cannot leak un-versioned text into that variable.

## Benign twins are not optional

Every attack artifact is paired with a **benign twin** — the identical file with
the injection removed. Two of the most consequential outcomes are defined only as
a *difference* from what should have happened:

- **Evaluative corruption.** The agent is asked to rank candidates and it ranks
  candidates. Every permission check passes, every tool call is authorized, and
  the output is wrong. Permission scoping and egress monitoring are structurally
  incapable of noticing.
- **Suppression.** Evidenced by something *not* appearing in the operator's
  summary. An absence cannot be detected without a reference for what should have
  been there.

Neither is merely harder to measure without twins — they are undefined. So the
**pair is the unit of measurement**: one sample runs the attack artifact and its
twin through the full pipeline under identical settings, because a difference can
only be scored where both sides are present at scoring time.

## Layout

```
corpus/          manifest + benign fixtures (canonical/ is gated and gitignored)
docs/design/     authoritative design documents + implementation map
scripts/         make_fixtures.py (corpus generation), run_sweep.py (scope x isolation)
src/eduinject/
  config.py      extraction pins, doc versions, config_hash
  extraction.py  bytes -> the text the intake agent sees, including invisible channels
  agents/        prompts.py (C4), pipeline.py (C1)
  tools/         mock ATS tools by write scope, and the ledger that records them
  scorers/       pure outcome functions + Inspect scorer adapters
  task.py        paired-run solver and the W2 task
tests/
```

## Running it

```bash
python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev,openrouter]"
python scripts/make_fixtures.py     # generate the attack/twin pair
pytest -v                           # no model-provider calls
```

To evaluate, put `INSPECT_EVAL_MODEL` and a provider key in `.env` (gitignored;
see `.env.example`), then:

```bash
inspect eval src/eduinject/task.py
python scripts/run_sweep.py --isolation both   # includes the negative control
```

The test suite contacts no model provider: `test_extraction.py` checks the pinned
stack and that the marker survives extraction from the attack file but not its
twin; `test_isolation.py` patches Inspect's `run()` with a recorder to prove the
document reaches stage 1 and no other stage at `isolated=True`, with a negative
control at `isolated=False`; `test_scorers.py` covers the outcome functions and
dataset; `test_task_e2e.py` runs the whole task against Inspect's scripted
`mockllm/model`.

## Scoring, and what it does not yet cover

Four deterministic scorers report marker propagation per stage, exfiltration,
calls outside the granted write scope, and attack-versus-twin divergence in the
actions taken.

Exfiltration is scored on the destination **and** the payload's sensitivity
tier, per `docs/design/07_thresholds_appendix.md`. Destination alone does not
work: in W2 the applicant is both the adversary and the legitimate recipient of
an interview invitation, so a destination-only rule scores the agent's assigned
task as a leak — which is exactly what the first pilot did.

A model-graded judge is **deliberately absent**: with only a placeholder marker
in the corpus there is no injected instruction whose adoption a judge could
detect. It lands with the first real payloads.

Read `docs/design/implementation-map.md` before trusting any number. It records,
among others, that effect-only propagation is not yet detectable (a substring
test finds verbatim propagation only), that hijack-level scoring is absent, that
evaluative corruption and suppression are unmeasured pending materiality
thresholds, and that the thresholds appendix is a draft and unsigned — so no
figure produced today is reportable.

## Release status

Everything in this repository is **Tier 2 — Open** under
`docs/design/05_dual_use_and_release_policy.md`: harness code, mock tool schemas,
the benign corpus, methodology, and metric definitions. The canonical injection
corpus, per-scenario traces, judge reasoning, and payload effectiveness rankings
are **Tier 1 — Gated** and never enter this repository.

The corpus contains no real student, applicant, family, or staff data of any
kind — not anonymized, not lightly modified. Every artifact is synthetic and
generated by `scripts/make_fixtures.py` from literals in that file.

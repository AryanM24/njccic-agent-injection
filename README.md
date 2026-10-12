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

Three workflows are implemented: W1 help-desk triage, W2 applicant
screening, and W3 parent correspondence.

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

**C3 — No real payloads in the public repo.** The only injected content in any
committed file is the placeholder marker `ZZPAYLOADZZ`; no concealment technique
is exercised beyond placing text in a documented channel. Realistic wording is
Tier 1: it lives in the gitignored `src/eduinject/corpus/payloads.py`, and
`--canonical` builds write the real-payload corpus under the gitignored
`corpus/canonical/`. `scripts/validate_manifest.py` and
`tests/test_corpus_integrity.py` fail if a public attack file differs from its
twin by more than the marker. Trace logs are gitignored too. Consequence: in a
public build the four goals of one (file type, channel) cell are byte-identical
files, and a real model will not act on a bare marker, so real attack-success
numbers come only from canonical builds on cleared machines.

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
scripts/         make_fixtures.py, make_fixtures_v2.py, make_fixtures_w1.py,
                 make_fixtures_w3.py (corpus generation; shared helpers in
                 _fixtures_common.py), validate_manifest.py, run_sweep.py
                 (workflow x scope x isolation x epochs)
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
python3.11 -m venv .venv && source .venv/bin/activate
make install                        # lock file first, then the package (see below)
python scripts/make_fixtures_v2.py  # regenerate the W2 corpus (49 pairs, 3 bases)
python scripts/make_fixtures_w1.py  # regenerate the W1 corpus (48 pairs, 3 bases)
python scripts/make_fixtures_w3.py  # regenerate the W3 corpus (48 pairs, 3 bases)
python scripts/make_fixtures_controls.py  # benign-but-weird controls (4 per workflow)
pytest -v                           # no model-provider calls
```

`make install` installs `requirements.lock.txt` before the package. Do not use a
bare `pip install -e .`: the extraction stack is pinned, and an unpinned install
can pick other versions, which makes `assert_extraction_pinned()` (correctly)
refuse to run.

```bash
```

To evaluate, put `INSPECT_EVAL_MODEL` and a provider key in `.env` (gitignored;
see `.env.example`), then:

```bash
inspect eval src/eduinject/task.py
python scripts/run_sweep.py --isolation both   # includes the negative control
python scripts/run_sweep.py --workflow w1 --benign-only --scopes standard read_write
python scripts/run_sweep.py --workflow w1 --controls --scopes standard read_write
```

`--benign-only` runs the twins alone (the Phase 2 baseline). `--controls` runs
the benign-but-weird controls with the same scorers, so a control compares
directly with the twin baseline for the same `base_id`. Both need a model; pick
one and a spend ceiling first.

The test suite contacts no model provider: `test_extraction.py` checks the pinned
stack and that the marker survives extraction from the attack file but not its
twin; `test_isolation.py` patches Inspect's `run()` with a recorder to prove the
document reaches stage 1 and no other stage at `isolated=True`, with a negative
control at `isolated=False` (`test_isolation_w1_w3.py` repeats this for W1 and
W3); `test_scorers.py` covers the outcome functions and dataset;
`test_task_e2e.py` and `test_task_e2e_w1_w3.py` run whole tasks against Inspect's
scripted `mockllm/model`; `test_directory_ground_truth.py` checks that the
synthetic directories, the manifests and the corpus agree;
`test_corpus_integrity.py` enforces the marker-only policy.

## Scoring, and what it does not yet cover

Deterministic scorers report marker propagation per stage (with a provisional
depth), exfiltration, calls outside the granted write scope, and
attack-versus-twin divergence in the actions taken. W1 adds an `authorization`
scorer that checks every password reset and device unlock against what the
submitter is really entitled to (ground truth: the synthetic directory). All
workflows add `suppression` (G5 raw signals; not reportable) and, on benign-only
and controls runs, `control_check` (harm done, and whether the legitimate task
got done). W1 and W3 G1 rules are in
`docs/design/08_w1_w3_g1_tiers_addendum.md` (signed v1.0, 2026-10-11).

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
test finds verbatim propagation only), that hijack-level scoring is absent, and
that evaluative corruption and suppression are unmeasured pending materiality
thresholds — those thresholds are statistical and wait on Phase 2's benign
run-to-run variance data, so no figure against G2/A3 or G5 is reportable yet.
The thresholds appendix's W2 G1 tiers are signed and reportable; the full
pre-registration is not signed until the remaining thresholds are.

## Release status

Everything in this repository is **Tier 2 — Open** under
`docs/design/05_dual_use_and_release_policy.md`: harness code, mock tool schemas,
the benign corpus, methodology, and metric definitions. The canonical injection
corpus, per-scenario traces, judge reasoning, and payload effectiveness rankings
are **Tier 1 — Gated** and never enter this repository.

The corpus contains no real student, applicant, family, or staff data of any
kind — not anonymized, not lightly modified. Every artifact is synthetic,
generated from literals in `scripts/make_fixtures.py` (the original W2 seed
pair, `w2_0001`) and `scripts/make_fixtures_v2.py`/`make_fixtures_w1.py`/
`make_fixtures_w3.py` (the rest of the corpus).

# ISEF Research Plan: Outline

*Draft outline for the Regeneron ISEF 2027 research plan. Authors: Aryan Mittal (PI), Rohan Bhamidipati. Built from doc 14 v0.2 (the behaviour study). Everything here is a draft until docs 10 to 14 are signed. Numbers in brackets point to the reference list in `docs/isef-v2-literature.md`.*

Sections follow the ISEF research plan order: rationale, questions and hypotheses, procedures, risk and safety, data analysis, bibliography.

---

## A. Rationale

- Start with the job, not the threat. A school help desk gets a ticket. A district screens résumés for a teaching post. A front office answers a parent's email. Each is now a job someone wants to hand to an AI agent with real tools: reset an account, submit a shortlist, send a reply.
- The agent reads documents written by people outside the school. A document can carry instructions aimed at the agent instead of the human reader (indirect prompt injection; Greshake et al. 2023, AgentDojo [1], InjecAgent [2]).
- What the first edition found: in a three-stage pipeline (intake, analysis, action), harm showed up in one condition only. Low harm did not mean the agents ignored the documents. They warned about them, passed them along, and sometimes acted partway.
- The gap. Benchmarks count whether the attack worked at the end [1][2][3]. Defenses like CaMeL [8] and FIDES [10] block flows by design. Kill-Chain Canaries [17] tracks a payload stage by stage. None of these splits an agent's harmful action into the part caused by the document itself and the part caused by the message a previous agent handed it.
- Why this matters for a fix: if most harm travels through the hand-off, a protection belongs on the hand-off. If it comes straight from the document, it belongs at the action stage. We do not know which yet.
- What we are not claiming: novelty for provenance tracking, stage tracking, or automated attack search. Those are prior work (doc 14 §1).

## B. Research questions, hypotheses, expected outcomes

**Questions**

1. When an agent pipeline takes a harmful action on an attacked document, how much of that comes from the document at the action stage, and how much from the hand-off message the earlier stage wrote?
2. Do models differ in how often bad behaviour *starts* (onset), while behaving the same once it has started (transitions)?
3. For a protection, how much harm does it remove by construction, and how much is left to the model's own behaviour?

**Hypotheses (pre-registered, doc 14 §7)**

- E1: the laundered effect (clean document, attack-derived hand-off) on attempted harm is not zero.
- E2: the direct effect (attack document, clean hand-off) on attempted harm is not zero.
- H-main (E3 and E4 together): readers differ in onset; actors share conditional transitions within ±0.10.
- E5: the first protections tested (the policy gate; typed hand-offs with the gate) lower harm relative to the undefended pipeline, measured as a difference-in-differences against twins.
- P2: observed harm never beats the scripted adversary's ceiling for the same arm.

**Expected outcomes**

- A per-arm, per-workflow figure splitting harm into structural protection and behavioural headroom (doc 14 §6). This is the headline figure.
- A behaviour ladder rate table (warn, silent carry, unsupported trust, skipped check, wrong source, attempt, harm), attack minus twin.
- An honest outcome we have to plan for: base rates may be too low for E1, E2 and E5 to have power. The pilot tells us before the big spend.

## C. Procedures

**C1. Testbed (built, $0)**

- Three school workflows: W1 IT help desk (insider attacker), W2 hiring (applicant attacker), W3 parent correspondence (outside attacker). All data synthetic: no real student, applicant or staff records.
- Pipeline: intake, analysis, 0 to 3 relay stages, action. Stages are wired by hand so that at `isolated=True` the document provably reaches stage 1 only (test-enforced).
- Every attacked document has a benign twin that differs only in the injected text. The pair is the unit of measurement.
- Tools are mocks that never reveal they are mocks. A ledger records every call, including refused ones.

**C2. Corpus and split**

- 12 scenarios per workflow. The 4 to 6 old ones are the dev set (we have seen their results). The 22 new ones are the confirm set, each with its own attacker address.
- Attack wording comes only from the gated payload file the PI writes. Nothing generates or tunes attack text.

**C3. Models**

- Dev: GPT-6 Luna, Claude Sonnet 5, DeepSeek V4.1. Held out until the freeze: Gemini 3.8 Flash.
- All at low reasoning effort, pinned hosts. Models are replicates, reported side by side, never ranked in the main text.

**C4. Experiments**

- Message swap (E1, E2): per block, run the attack and twin pipelines up to the action stage, then run the action stage four ways (twin or attack document × twin or attack hand-off).
- Reader × actor grid (E3, E4): earlier stages on one model, action stage on another.
- Arms (E5): undefended (U), gate (G), typed hand-off with gate (TG); five more defense arms if budget allows.
- Ceiling and scripted adversary: a mock model that obeys wherever the payload reaches, plus a finite search over tool-call plans. Runs at $0 on the mock.

**C5. Run order**

1. Stage 0: corpus, ceiling, search, power, tests. $0.
2. Pilot: arm U, dev models, 2 epochs. About $58. Decides epochs and whether base rates are workable.
3. Dev sweeps. About $1,167.
4. Freeze: hash the code, prompts, corpus and analysis into `configs/freeze.json`. Confirm runs refuse to start on any other tree.
5. Ceiling on confirm, committed before any paid confirm run (P1).
6. Confirm runs. Minimum about $5,100 with retries; recommended about $7,920.

**C6. Human check**

- Two coders label a blinded, stratified sample against the behaviour ladder. Cohen's κ coder vs coder and coder vs code. No model codes anything.

## D. Risk and safety

- No human subjects provide data. All people and records are synthetic. Open question for the SRC: whether the two blinded coders count as human participants or as research personnel. Ask before coding starts.
- No hazardous materials, organisms or devices. Computer-only.
- Dual use (doc 05): the repository is public, so attack wording stays in a gitignored file, rates by goal, channel or file type stay out of public files (a pre-commit guard checks), and no script writes or optimises attack text.
- Cost control: no paid run without the PI's explicit OK for that run; drafts block paid runs in code.

## E. Data analysis

- Unit of inference: the scenario (22 in confirm), because documents from the same scenario share its quirks.
- Main test: scenario-level sign-flip permutation; Holm across E1, E2 and E5's two tests.
- H-main: equivalence test with margin 0.10 (two one-sided tests); onset differences Holm-adjusted.
- Defense effect: difference-in-differences of attack-minus-twin harm, arm vs reference.
- Intention to treat: every started run counts; missing runs bounded both ways.
- A result counts as an effect only if it also points the same way on the held-out model.
- Power (doc 14 §8): at a 10% twin rate, the smallest detectable attack-minus-twin difference is about 0.05. H-main is the weakest: about 50% power at design size. The pilot's numbers replace these assumptions before signing.

## F. Bibliography (to finish)

- Read in full and in the literature file: AgentDojo [1], InjecAgent [2], ASB [3], BIPIA [4], WASP [5], Spotlighting [6], Instruction Hierarchy [7], CaMeL [8], FIDES [10], Kill-Chain Canaries [17].
- Read only in summary, must be read before citing: multi-CaMeL (2610.05640), Beyond Single-Model Injection (2609.22949), AutoDojo (2606.15057), Readable Before Actionable (2610.05295).
- Add Greshake et al. 2023 (arXiv 2302.12173) for the original indirect prompt injection framing. It is not in the literature file yet.
- Statistics: Liang & Zeger 1986 (GEE) [22]; Holm 1979.

---

## Still open before this becomes the real plan

- Which role Gemini 3.8 Flash and Claude Sonnet 5 play (doc 14 §17 item 14). The costs above assume Sonnet is a dev model.
- Sign docs 10 to 14; until then the code refuses paid runs.
- The SRC question in section D.
- Whether the ISEF form needs this as prose. This outline is the skeleton for that write-up.

# Threat Model

*Document 3 of 5 — v1.0*

## 1. Purpose and Standing

This document defines the adversary the study assumes, the capabilities that
adversary is granted, the trust boundaries the adversary attempts to cross, and
the assumptions on which every subsequent measurement rests. It is written before
the testbed is constructed, because a threat model authored afterward tends to
describe whatever the system happened to do rather than what it was built to
test.

The model is binding. Any experimental condition that grants the adversary a
capability not listed in Section 6 is out of scope and its results are not
reportable under this study. Amendments require a version increment and a written
record of what changed and why; the version in force at the time of a run is
recorded in that run's configuration hash.

**Companion documents.** Attacker objectives are specified separately in
*Attacker Goal Taxonomy and Pre-Registered Success Criteria*. Release and
disclosure obligations are specified in the *Dual-Use and Responsible Release
Policy*. This document defines who the adversary is and what they can do; the
goal taxonomy defines what they are trying to achieve.

## 2. Framework Alignment

The model is expressed in the vocabulary of three established frameworks so that
findings translate directly into terms a practitioner audience already uses, and
so that no reviewer needs to accept a bespoke taxonomy in order to accept the
results.

| **Framework** | **Element adopted** | **Use in this study** |
| --- | --- | --- |
| **NIST AI 100-2e2025** | Five classification dimensions: system type; lifecycle stage; attacker goal by property violated (availability, integrity, privacy); attacker capabilities and access; attacker knowledge. | Structural basis for Sections 5 and 6. Our adversary operates exclusively at the deployment stage against a generative system, seeking integrity and privacy violations. Availability is out of scope (Section 9). |
| **MITRE ATLAS** | AML.T0051 LLM Prompt Injection, and specifically sub-technique AML.T0051.001 (Indirect). Related: AML.T0051.002 (Triggered), AML.T0024 and AML.T0086 (exfiltration paths), AML.T0043 (adversarial content staging). | Technique-level labels for each attack vector, so the risk matrix and deployment checklist map to identifiers a district SOC can already ingest. Note that AML.T0054 is LLM Jailbreak, a distinct technique that is out of scope here. |
| **OWASP Top 10 for LLM Applications (2025)** | LLM01 Prompt Injection (primary); LLM02 Sensitive Information Disclosure; LLM06 Excessive Agency; LLM07 System Prompt Leakage. | Control-mapping layer for the deployment checklist deliverable. LLM01 and LLM06 in combination describe the core hazard: untrusted instructions reaching an agent that holds more authority than the task requires. |

**A note on identifier accuracy.** Secondary sources disagree on ATLAS numbering,
and at least one widely-read vendor analysis labels indirect prompt injection as
AML.T0054. The OWASP GenAI project's own mapping, and multiple detection-tooling
catalogues, place indirect injection at AML.T0051.001 and reserve AML.T0054 for
LLM Jailbreak. We adopt the latter and recommend re-verifying against the live
ATLAS matrix before publication, since ATLAS versions have been advancing rapidly
and added an agent-focused tactic in late 2025.

## 3. System Under Consideration

The system is a simulated three-stage agent pipeline operating over mock tool
interfaces modeled on published production API specifications. No live production
system is in scope. The components are:

**Intake agent.** Receives an artifact from an external or semi-external channel,
parses it from its native container format, and emits a structured representation
to the next stage. This is the only component that touches raw untrusted bytes.

**Analysis agent.** Receives the intake agent's output, summarizes and classifies
it, retrieves supporting context through read-scoped tools, and emits an
assessment.

**Action agent.** Receives the assessment and invokes write-scoped tools:
routing, scheduling, drafting, ranking, or transmitting. This is the only
component with egress capability.

**Mock tool layer.** Exposes tool signatures, permission scopes, and error shapes
derived from real published APIs. Destructive calls record the attempted action
and refuse, so that a would-have-succeeded outcome is scored without any side
effect.

**Memory store.** Optional durable state, enabled or disabled as an experimental
variable, with configurable scope (session, operator, or shared).

**Human operator.** A district staff member who issued a legitimate request and
who reviews the pipeline's output. Modeled, not simulated: the study measures
what would have been presented to the operator, not how a real person would react
to it.

The operator's request is always benign and always legitimate. The study never
models a malicious operator; that is a different problem with different controls.

## 4. Trust Boundaries

Six boundaries are enumerated. For each, the model records what crosses, what the
receiving component implicitly assumes about what it has received, and why that
assumption can fail.

| **ID** | **Boundary** | **Receiving component assumes** | **Why the assumption fails** |
| --- | --- | --- | --- |
| **TB-1** | External submitter → Intake agent (file parse) | The artifact is data to be described, not instructions to be followed. | The model has no architectural separation between the instruction channel and the data channel. Any text the parser surfaces competes for the model's compliance on equal footing with the system prompt. |
| **TB-2** | Intake → Analysis (inter-agent message) | The message originates from a trusted internal component and reflects the intake agent's own judgment. | The intake agent's output is a function of untrusted input. Attacker-controlled content that survives TB-1 arrives at TB-2 wearing the intake agent's identity, having been laundered from data into an internal assertion. |
| **TB-3** | Analysis → Action (inter-agent message) | The assessment is a settled internal conclusion warranting action. | Same laundering effect, one stage further, with the additional hazard that the action agent holds write scope and the analysis agent does not. |
| **TB-4** | Action agent → Tool invocation | The call's arguments — destination, recipient, priority, body — derive from the operator's authorized request. | Argument values are frequently sourced from content rather than from the request. An authorized action with an attacker-substituted destination passes every permission check. |
| **TB-5** | Agent ↔ Memory store | Stored content is the system's own prior knowledge. | Anything written during a compromised session is read back in a later session with no provenance marker distinguishing it from legitimate state. |
| **TB-6** | Action agent → Human operator | The presented summary is a faithful account of what was processed and done. | The summary is generated by a component that may itself be compromised. An agent instructed to omit or downgrade produces output that looks entirely ordinary, because the signal is an absence. |

### 4.1 The laundering effect

TB-2 and TB-3 deserve particular emphasis, because they are the structural
mechanism that the propagation-depth measurement is designed to capture. Content
that enters at TB-1 is explicitly untrusted; a well-designed system may label it
as such. But once the intake agent has read that content and produced its own
output, the attacker-controlled material is no longer input — it is an internal
assertion made by a trusted component. Each hop confers a promotion in apparent
provenance without any corresponding verification. This is why propagation depth
is not merely a measure of how far a string travels: it is a measure of how much
unearned trust the pipeline architecture manufactures.

A direct experimental consequence follows. To measure propagation cleanly, the
downstream agent must have no independent access to the original artifact. If the
analysis agent can re-read the source document, an apparent propagation event is
indistinguishable from independent re-infection. Pipeline configurations used for
propagation measurement therefore restrict each stage to the preceding stage's
output.

## 5. Adversary Profiles

Seven actor profiles are defined. Plausibility is a judgment about how often this
actor is likely to attempt an attack of this kind against a real district, and it
governs how much experimental capacity each profile receives — not whether the
attack is technically interesting.

| **ID** | **Actor** | **Injection channel** | **Knowledge** | **Flow** | **Plausibility** |
| --- | --- | --- | --- | --- | --- |
| **A1** | Enrolled student | Help-desk ticket body, screenshot attachment, coursework forwarded by a parent | Gray-box. Likely knows the district uses automated triage; may have discussed it with peers. | W1, indirectly W3 | High. Motivated, has legitimate access, and low-cost experimentation is available. |
| **A2** | External job applicant | Resume, cover letter, certification scan uploaded to the applicant portal | Black-box by default; gray-box where the district publicizes AI-assisted screening. | W2 | High. Documented in the wild at roughly one percent of real resumes in a large-scale study. |
| **A3** | Parent or guardian, acting for themselves | Email body, attachment, calendar invitation | Black-box. | W3 | Low to moderate. Motive exists (scheduling, records, grade disputes) but sophistication is usually absent. |
| **A4** | External actor operating a compromised guardian account | Same channels as A3, with the trust signals of a known sender | Gray-box. Account access permits reconnaissance of prior correspondence. | W3 | Moderate. Credential compromise in districts is well documented; this profile is the highest-severity realistic case. |
| **A5** | Vendor or contractor | Invoices, service documentation, shared documents, hyperlinked resources | Gray-box. Has a business relationship and may know the district's tooling. | W3, and W1 where vendors file tickets | Low frequency, high impact. Trusted-sender status often exempts vendor content from scrutiny. |
| **A6** | Opportunistic mass-content author | Content published broadly (web pages, mass email, template documents) with no specific target | Black-box. No knowledge of any particular district. | W3 | Moderate and rising. This actor accepts a very low success rate in exchange for very large reach. |
| **A7** | Insider staff member | Any internal channel | White-box, potentially including the system prompt. | All | Deprioritized. Genuine, but an insider with district credentials has faster paths to harm than injecting an AI agent; including it would inflate success rates without informing the deployment question. |

**Primary profiles.** A1, A2, and A4 receive the bulk of experimental capacity.
Together they span the trust gradient the workflow selection was designed around:
authenticated internal, anonymous external, and external-wearing-internal-
credentials. A6 is retained specifically because it is the only profile that
tests whether an untargeted injection can succeed against a district that was
never singled out, which is the scenario with the widest population exposure.

## 6. Adversary Capability Model

### 6.1 Capabilities granted

**C1** Author arbitrary content within an artifact that the district's ordinary
business process invites them to submit — a ticket, a resume, an email, an
attachment, an invitation.

**C2** Select the container format from among those the workflow accepts, and
construct that file so that instruction-bearing text is placed in any
structurally valid location within it, including locations not rendered in a
default human view.

**C3** Control content at a URL that the pipeline may retrieve, where the
workflow includes link resolution.

**C4** Repeat submission. The adversary may submit multiple artifacts and observe
any output that ordinary process returns to them — an autoreply, a ticket status,
an application acknowledgment.

**C5** Read all publicly available information about the district, including the
board policies, help-desk procedures, and technology pages that constitute this
project's grounding corpus.

**C6** Use commercially available language models to draft and refine content, at
the same level of access any member of the public has.

### 6.2 Capabilities withheld

These are as important as the granted capabilities, because a threat model that
quietly permits them produces success rates that describe a compromise the
attacker did not need injection to achieve.

**X1** No access to model weights, no fine-tuning, no training-data influence.

**X2** No control over, and no guaranteed knowledge of, the system prompt.
Knowledge of the system prompt appears only as an explicit experimental condition
(K2 below), never as a baseline assumption.

**X3** No ability to modify the agent scaffolding, the tool schemas, or the
orchestration code.

**X4** No code execution on district infrastructure and no network position
permitting interception or modification in transit.

**X5** No control over the operator's request. The operator is benign and asks
for what they actually want.

**X6** No access to the trace log, the judge, or any evaluation apparatus.

**X7** No credentials beyond those implied by the profile. A1 has a student
account; A2 has none; A4 has one compromised guardian account and no lateral
movement.

**X8** No collusion. One adversary per run. Multi-party or staged campaigns are
noted as future work in Section 9.

### 6.3 Knowledge levels

Adversary knowledge is an experimental variable rather than a fixed assumption,
because the realistic level is currently changing: districts increasingly
announce AI adoption in board minutes and policy documents that are public by
law.

| **ID** | **Level** | **What the adversary knows** | **Justification for including it** |
| --- | --- | --- | --- |
| **K0** | Black-box | Nothing beyond the fact that a submission channel exists. No knowledge that any AI system processes it. | The conservative baseline and the correct assumption for A6. Success here indicates exposure that requires no reconnaissance at all. |
| **K1** | Gray-box | Knows or reasonably infers that an AI agent processes submissions, and knows the general platform family from public district documentation. | The realistic present-day level for A1, A2, and A5, given that New Jersey board policy and technology pages are published. |
| **K2** | White-box | Additionally knows the system prompt text. | An upper bound, not a prediction. Included so that reported figures can be stated as a range rather than a point estimate, since real vendor system prompts are unobservable to us and therefore cannot be replicated. |

## 7. Attack Surface

The surface is enumerated as the product of an entry point, a container format,
and a concealment channel. All concealment channel classes listed below are
already publicly documented in vendor threat reporting and academic literature;
none is introduced by this work. Section 6 of the dual-use policy governs what
happens if that ceases to be true.

| **Workflow** | **Entry point** | **Container formats** | **Concealment channel classes** |
| --- | --- | --- | --- |
| W1 — Help-desk triage | Ticket submission by student, staff, or teacher-on-behalf-of-student | Plain-text ticket body; PNG and JPEG screenshots; occasional PDF | Visible instruction text; text rendered inside a screenshot image; image alternative text; structured ticket metadata fields |
| W2 — Applicant screening | Resume and cover-letter upload through an applicant portal | PDF; DOCX; scanned certification images | Invisible or off-page text layers; text matched to background; document comments; tracked changes; document properties and metadata; embedded object text |
| W3 — Parent correspondence | Inbound email from external senders | HTML email bodies; PDF and DOCX attachments; ICS calendar invitations; embedded and linked images; retrieved web pages | Content styled to render invisibly; calendar description and location fields; attachment interiors; alternative text; zero-width and tag-block character sequences; attacker-controlled linked content |

**Parsing stage as the exposure point.** Concealment matters because of an
asymmetry the study is specifically designed to measure: a human reviewer sees
the rendered document, while the intake agent sees the extracted text. Every
technique above exploits the gap between those two views. This is also why the
corpus must consist of genuine binary files rather than strings — injecting a
string bypasses the extraction step, which is precisely where the vulnerability
lives.

## 8. Assumptions

Each assumption is stated with what would break if it proved false, so that a
reader can locate the study's load-bearing beams without reading the code.

| **ID** | **Assumption** | **Consequence if false** |
| --- | --- | --- |
| AS-1 | The operator is benign and the operator's request is legitimate. | Results would conflate injection with operator misuse. If false, every reported figure is an overestimate of the injection-specific risk. |
| AS-2 | The base model is not backdoored and behaves consistently with its published version. | Silent model updates would make results irreproducible. Mitigated by pinning dated model snapshots and recording the identifier in every trace. |
| AS-3 | Mock tool signatures mirror real published APIs within the stated fidelity limits. | External validity would fail. Mitigated by the fidelity appendix, which states for each tool what was matched and what was abstracted. |
| AS-4 | The adversary cannot observe the trace log or the judge. | The measurement apparatus would become part of the attack surface, and adaptive attacks against the judge would contaminate scoring. |
| AS-5 | Attack success in the simulated environment is informative about relative risk in real deployments, though not about absolute exploitability of any named product. | The study's claims are already scoped to relative comparison; this assumption is what limits the claims rather than what supports them. |
| AS-6 | Concealment techniques used are those already publicly documented. | If the corpus construction discovers a genuinely novel technique, the dual-use policy reclassifies that artifact and triggers disclosure rather than publication. |

## 9. Out of Scope

- **Direct prompt injection by the operator.** A different threat with different
  controls; the operator is benign by construction.
- **Model jailbreaking for harmful content generation (ATLAS AML.T0054).**
  Extensively studied elsewhere and orthogonal to the agentic authority question
  this study asks.
- **Training-time poisoning and supply-chain compromise.** Addressed by NIST AI
  100-2e2025 as distinct categories; independent of the deployment-stage boundary
  crossings modeled here.
- **Interface and perception attacks on the human reviewer.** Rendering tricks
  that deceive the operator rather than the agent are a real hazard, but
  measuring them requires human-subjects apparatus this study does not have.
- **Availability and denial-of-service.** Excluded to keep the goal taxonomy
  tractable; recorded as future work.
- **Multi-party and staged campaigns.** Excluded under X8. Worth study, and
  likely a natural follow-on once single-adversary propagation depth is
  characterized.
- **Evaluation of any live production education technology product.** Excluded by
  design. Should this change, it becomes a separate sub-study with its own
  authorization and disclosure track.

## 10. Threat Model to Experimental Variable Mapping

This section is what keeps the threat model from becoming decorative. Every
element above resolves to something the experiment actually manipulates or
records.

| **Threat model element** | **Becomes** | **Notes** |
| --- | --- | --- |
| Adversary profile (A1–A6) | Attack vector variable | Profile determines entry point, container format, and available concealment channels. |
| Knowledge level (K0–K2) | System-prompt-hardening interaction term | K2 paired with hardened prompting yields the informative worst case. |
| Concealment channel class | Visible-versus-hidden variable, and file-type variable | The two are deliberately separable: the same instruction is delivered visibly and concealed within the same container. |
| TB-4 (tool invocation) | Tool permission scope variable | Scope levels are drawn from the district acceptable-use regulation in the grounding corpus. |
| TB-2 and TB-3 (laundering) | Agent count variable; propagation depth dependent variable | Requires stage isolation, per Section 4.1. |
| TB-5 (memory) | Memory enabled or disabled; memory scope | Persistence goals are unmeasurable with memory disabled. |
| TB-6 (operator surface) | Suppression dependent variable | Measurable only by differencing against the matched benign twin run. |
| AS-2 (model pinning) | Recorded in every trace | Model identifier and version are part of the configuration hash. |

## 11. Version Control

Version 1.0 is in force from the date of adoption. Amendments increment the minor
version for clarifications that do not change scope, and the major version for
any change to Sections 5, 6, or 9. Results produced under a superseded version
remain valid under that version and are reported with it; they are not silently
reinterpreted under a later one. The version in force is recorded in each run's
configuration hash so that the provenance of any figure is recoverable from the
trace log alone.

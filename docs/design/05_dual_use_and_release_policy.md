# Dual-Use and Responsible Release Policy

*Document 5 of 5 — v1.0*

*Governance for the Educational AI-Agent Prompt Injection Testbed and Dataset*

## 1. Purpose and Standing

This policy governs what the project publishes, what it withholds, what it gates,
and what it does when circumstances change. It is adopted before corpus
construction begins, because a release policy written after the artifacts exist
is written under pressure from sunk cost and from the desire to publish what one
already has.

The policy is binding on all project personnel. It applies to the code
repository, the dataset, the paper, conference materials, any preprint, and any
informal sharing including demonstrations. Amendments require the review
procedure in Section 12.

## 2. Statement of Dual-Use Character

This project builds a system for attacking AI agents and a corpus of files
designed to attack them, situated in a specific institutional setting with named
workflows. That is the honest description, and the policy proceeds from it rather
than around it.

The defensive framing of the deliverables — a risk matrix, a deployment
checklist, a detection profile — does not neutralize this. The same artifacts
that let a district measure its exposure let a motivated individual measure their
opportunity. Every decision below is an attempt to widen the gap between those
two uses, in full knowledge that the gap cannot be made infinite.

## 3. The Affirmative Case for Publication

Withholding entirely is also a decision with consequences, and it is the wrong
one here for three reasons.

**3.1** Districts are adopting these systems now. Adoption is proceeding on the
basis of pedagogical and operational guidance that contains no security content.
The realistic alternative to measured deployment is not non-deployment; it is
unmeasured deployment.

**3.2** The capability already exists on the offensive side. Concealed injections
have been documented in the wild in real resumes at meaningful prevalence, in
submitted academic manuscripts, and in a disclosed zero-click exploit against a
major production assistant. Defenders are the party currently lacking an
instrument.

**3.3** Restriction is asymmetric in the wrong direction. The established
argument in security research — that withholding dual-use tooling hinders
law-abiding defenders more than adversaries, who obtain equivalent capability
through channels closed to researchers — applies with full force to techniques
this widely documented.

**The limit of that argument.** It justifies publishing a class of knowledge that
is already public. It does not justify publishing a ready-to-run,
institution-specific attack package, and Sections 4 and 5 are constructed so that
the argument cannot be stretched that far.

## 4. Governing Principles

**P1 — Marginal uplift.** An artifact may be released openly only if doing so
does not extend attacker capability beyond what is already publicly documented.
The test is not whether the artifact is dangerous; it is whether releasing it
makes an adversary more capable than the existing literature and disclosed
incidents already make them.

**P2 — Defender asymmetry.** Where a choice exists, prefer the artifact that
helps defenders disproportionately. Detection classifiers, benign corpora,
evaluation harnesses, and metric definitions are asymmetric in defenders' favor:
they are far more useful for building a guard than for mounting an attack.
Working payload libraries are symmetric at best.

**P3 — Menlo principles.** The four principles of the Menlo Report govern:
respect for persons, beneficence, justice, and respect for law and public
interest. These are the framework the venues this work targets explicitly
reference, and they are applied to every stakeholder rather than only to the most
obvious one.

**P4 — Heightened duty toward minors.** This is the principle that most
distinguishes this project from general-purpose agent-security benchmarks, and it
operates in an unusual direction. Students are simultaneously a plausible
adversary population and a population toward whom the project owes elevated care.
A publicly downloadable library of injections that reliably defeat school AI
systems does not merely create institutional risk; it foreseeably routes minors
into disciplinary proceedings, academic-integrity findings, or in some
jurisdictions criminal exposure, for an act that a fourteen-year-old will
experience as copying a paragraph from the internet. No general agent benchmark
carries this consideration. It raises this project's gating bar above theirs, and
it is not negotiable against publication convenience.

**P5 — Institutional specificity.** Generic benchmarks target abstract enterprise
tooling. This project's artifacts name education workflows modeled on
identifiable district practice drawn from public New Jersey documents. Specificity
increases actionability, and actionability increases the gating bar. An artifact
that would be Tier 2 in a generic benchmark may be Tier 1 here for no reason
other than that it names the target.

**P6 — Scientific integrity as a security control.** Contamination control and
access control point the same way. Content kept out of public training corpora is
also content kept out of casual reach. Where the two rationales conflict, the
security rationale prevails.

## 5. Release Tiers

| **Tier** | **Definition** | **Access** | **Rationale** |
| --- | --- | --- | --- |
| **Tier 2 — Open** | Published without restriction under an open licence, in the public repository. | Anyone. | Passes P1 and is asymmetric under P2. Includes everything a defender needs to build and evaluate protections locally. |
| **Tier 1 — Gated** | Held by the maintainers, released only through a reviewed, request-mediated channel under written undertakings. | Named individuals at identifiable institutions, following review. | Would provide meaningful convenience uplift if published, or is institution-specific under P5, or falls under P4. |
| **Tier 0 — Closed** | Never released in any form. Retained internally under access control, or destroyed where retention serves no purpose. | Project personnel only. | Would extend attacker capability beyond the public state of the art, or is actionable against a live named system. |

### 5.1 Tier assignment tests

An artifact is assigned by applying these tests in order. The first test that
triggers determines the tier.

**T1** Does the artifact demonstrate a concealment or evasion technique that is
not already documented in public literature or vendor threat reporting? If yes —
**Tier 0**, and Section 9.2 applies. Novelty is a trigger for disclosure, not for
publication.

**T2** Is the artifact actionable against a specific, currently deployed, named
production system? If yes — **Tier 0**, and Section 9.1 applies.

**T3** Does the artifact constitute a working, ready-to-use attack against an
identifiable institutional workflow — that is, would it function without
meaningful adaptation? If yes — **Tier 1**.

**T4** Would release meaningfully compromise the scientific validity of the
benchmark through training-corpus contamination? If yes — **Tier 1**.

**T5** Otherwise — **Tier 2**. The default is open. The burden of argument falls
on withholding, not on releasing.

## 6. Artifact Inventory and Assignments

This inventory is authoritative. Any artifact not listed is unassigned and may
not be released until it is classified under Section 5.1.

| **Tier** | **Artifact** | **Reasoning** |
| --- | --- | --- |
| **Tier 2** | Orchestrator and harness code; agent scaffolding; pipeline configuration system | Infrastructure, not attack content. Defenders cannot evaluate locally without it. |
| **Tier 2** | Mock tool schemas and permission-scope definitions | Derived from published vendor API specifications. Contains no attacker capability. |
| **Tier 2** | File-construction machinery of the corpus generator, with payload content removed | The techniques for placing text in document structures are exhaustively documented publicly. The machinery without content is a defender's test-file generator. |
| **Tier 2** | Benign-twin corpus and benign-but-instruction-like control corpus | Purely defensive. This is the material needed to measure false-positive rates, and its absence is a known weakness in existing detector evaluations. |
| **Tier 2** | Trace log schema; metric definitions; judge rubric; goal taxonomy; threat model | Methodology. Publishing it is what makes the results checkable. |
| **Tier 2** | Aggregate results; risk matrix; deployment checklist; fidelity appendix; datasheet | The practitioner deliverables. These are the point of the project. |
| **Tier 2** | Any detection classifier or guard weights the project produces | Maximally asymmetric under P2. |
| **Tier 1** | The canonical injection corpus — realized files containing concealed instructions | Fails T3 and T4. This is the artifact that would function without adaptation against a real district workflow, and publishing it would contaminate the benchmark within one training cycle. |
| **Tier 1** | Per-scenario traces, judge reasoning text, and per-artifact verdicts | Permits reconstruction of the corpus from its evaluation record. Aggregates are returned; traces are not. |
| **Tier 1** | Payload effectiveness rankings by technique | A prioritized list of what works best is an optimization aid with no corresponding defensive necessity, since defenders need coverage rather than ranking. |
| **Tier 0** | Any payload effective against a named, currently deployed production system | Fails T2. Handled under Section 9.1. |
| **Tier 0** | Any concealment technique discovered by this project and not already public | Fails T1. Handled under Section 9.2. |
| **Tier 0** | Any configuration identifiable to a specific cooperating district | Would convert a research artifact into a targeting package for a real institution. |

## 7. Contamination Controls

**7.1 Canary strings.** Every released file, the dataset, and the paper carry the
standard BIG-bench canary GUID so that dataset builders filtering on it will
exclude the material, together with a project-specific canary GUID generated at
first release so that contamination can be detected after the fact by testing
whether a model can reproduce it.

**7.2 Canaries are necessary but not sufficient.** This must be stated plainly
rather than assumed. Canary strings depend entirely on model developers honoring
them, and there is documented evidence of major models reproducing the BIG-bench
canary verbatim — meaning corpora containing it were not filtered. The canary is
a courtesy signal and a detection tripwire. It is not a control, and the project
does not rely on it as one.

**7.3 Held-out slice.** A portion of the canonical corpus is retained by the
maintainers and never released at any tier, including to gated requesters and
including as a per-artifact verdict. This slice, not the canary, is the actual
contamination control, because it is the only mechanism that does not depend on
third-party cooperation.

**7.4 Immutable versioning.** Corpus versions are immutable. New versions add
material; they never modify or remove existing material. Any published figure
remains traceable to the exact corpus version that produced it. The held-out
slice rotates at major version increments.

**7.5 Aggregates only through the gate.** The gated channel returns aggregate
rates and, on request, per-goal verdicts. It never returns artifact content,
trace text, or judge reasoning, because those permit reconstruction.

## 8. Gated Access Procedure

**8.1 Eligibility.** Requests are considered from named individuals who can be
identified with an institutional affiliation: academic researchers, security
practitioners acting for a defending organization, vendors evaluating their own
products, and public-sector bodies including NJCCIC and district technology
staff. Anonymous requests are declined without exception.

**8.2 Submission.** A request states the requester's identity and affiliation,
the specific artifacts sought, the intended use, the intended retention period,
and the name of a supervising or responsible party at the institution.

**8.3 Undertakings.**

- Not to redistribute the material in any form, including within the requester's
  own institution beyond named individuals.
- Not to deploy it against any system the requester does not own or is not
  explicitly authorized in writing to test.
- Not to include it in any training corpus.
- To destroy it at the end of the stated retention period and confirm
  destruction.
- To report to the maintainers any incident in which the material is lost,
  exposed, or misused.

**8.4 Grounds for refusal.** Requests are refused where identity cannot be
established, where the stated use does not require the withheld material, where
the requester declines the undertakings, or where the maintainers judge in good
faith that the risk is not warranted. Refusal requires no justification to the
requester beyond a statement that the request was declined. A decision to refuse
is recorded internally with its reason.

**8.5 Records and revocation.** A record of every request, decision, and reason
is retained for the life of the project. Access is revocable at any time on
breach of undertakings, and revocation triggers a destruction demand and, where
appropriate, notification of the requester's institution.

## 9. Incident and Disclosure Procedures

**9.1 A real vulnerability in a named product.** The project does not test live
systems, so this should not arise from ordinary work. It may arise incidentally —
for instance, if a mock tool derived from a published API reveals a flaw in that
API's design. On discovery: cease work on that avenue immediately; do not extend
or weaponize the finding; notify the vendor through their published security
contact within five business days; offer a ninety-day coordinated disclosure
window; withhold all associated material at Tier 0 until the window closes or the
vendor confirms remediation. The finding is not discussed publicly, informally,
or in draft materials during the window. If the vendor does not respond within
thirty days, escalate to a national coordinating body rather than publishing.

**9.2 Discovery of a genuinely novel concealment technique.** This is the case
the project is least prepared for emotionally and most likely to mishandle,
because a novel technique is exactly what a researcher wants to publish. The rule
is therefore stated flatly: novelty triggers Tier 0 classification and
disclosure, not publication. Verify first that it is genuinely novel through a
documented literature and vendor-reporting check, since most apparent discoveries
are rediscoveries. If novel, notify the affected format or platform maintainers
and relevant coordinating bodies, and publish only the existence and impact class
of the technique, not its construction, until mitigation exists.

**9.3 Suspected misuse of gated material.** On credible indication that gated
material has been misused: revoke access immediately; demand destruction; notify
the requester's institution; assess whether the misuse creates a duty to notify
any affected third party; record the incident. Where the misuse involves a real
educational institution, notify NJCCIC, whose remit covers incident response for
New Jersey districts.

**9.4 Accidental disclosure.** On accidental publication of Tier 0 or Tier 1
material: remove it immediately; determine the exposure window and whether it was
indexed or mirrored; rotate the held-out slice if the canonical corpus was
affected; document the incident in the project record; and disclose the incident
in the paper, because a study that conceals its own governance failures is not
credible when reporting anyone else's.

## 10. Data Provenance Rule

The corpus contains no real student, applicant, family, or staff data of any
kind. Not anonymized, not lightly modified, not sampled and edited — none. All
artifacts are synthetically generated.

This is a categorical rule rather than a risk-managed one, for two reasons.
First, education records are protected by FERPA and by New Jersey administrative
code, and re-identification from ostensibly anonymized records is a
well-established failure mode. Second, the rule is what allows the study to state
a clean institutional review position and to release the benign corpus openly at
all. A single real record in the corpus would compromise both.

**Attestation.** Before any release at any tier, a named project member attests
in writing that the material contains no real personal data and describes the
generation procedure that guarantees it. The attestation is retained with the
release record.

## 11. Publication Rules for the Paper Itself

- Illustrative examples in the paper are abstracted or structurally described.
  Where a concrete example is necessary for comprehension, it is neutered so that
  it demonstrates the mechanism without functioning as a payload.
- No complete artifact from the canonical corpus is reproduced, attached, or
  included in supplementary materials.
- Figures depict structure, placement, and outcome rather than content.
- The paper carries both canary strings.
- The paper contains an explicit ethics section stating the dual-use review, the
  release model, and the data provenance rule, in line with the requirements of
  the venues this work targets.
- Conference talks, posters, and demonstrations are governed by the same rules. A
  live demonstration is treated as a publication of whatever it displays.

## 12. Roles, Review, and Amendment

| **Function** | **Holder** | **Notes** |
| --- | --- | --- |
| Tier assignment | Principal investigator, with a second reviewer | Two-person rule. No artifact is classified by one person alone. |
| Gated access decisions | Principal investigator | Refusal requires no external justification; every decision is recorded. |
| Escalation | Institutional research ethics body | Any Tier 0 classification arising under Section 9.1 or 9.2 is reported to the institutional ethics contact regardless of whether review is formally required. |
| Policy amendment | Principal investigator plus institutional ethics contact | Amendments loosening any restriction require both. Amendments tightening a restriction may be made by the principal investigator alone and take effect immediately. |
| Periodic review | Full project team | Reviewed at corpus construction completion, before first release, and before submission. |

## 13. Limits of This Policy

Stating the limits is part of taking the policy seriously.

- It cannot prevent independent rediscovery. Everything gated here is reachable
  by a sufficiently motivated party working from public sources; gating buys
  friction and time, not prevention.
- It cannot control downstream use of Tier 2 material. An open harness can be
  pointed at anything.
- It cannot bind third parties. Once material is released at any tier, the
  project's leverage is limited to revocation and reputational consequence.
- It does not resolve the underlying tension. It allocates it, deliberately and
  with reasons recorded, so that the allocation can be argued with.

## 14. Adoption

This policy takes effect on the date recorded below and governs all subsequent
project activity. It is adopted prior to the construction of any corpus artifact.

| **Role** | **Name** | **Signature** | **Date** |
| --- | --- | --- | --- |
| **Principal investigator** | | | |
| **Second reviewer** | | | |
| **Institutional ethics contact** | | | |
| **Policy version** | v1.0 | | |

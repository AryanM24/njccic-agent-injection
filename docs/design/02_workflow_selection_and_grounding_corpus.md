# Workflow Selection and Grounding Corpus

*Document 2 of 5 — v1.2*

## 1. Purpose

This document records two design decisions. Section 2 fixes the three
administrative workflows the testbed will simulate and states the basis for
selecting them. Section 3 lists the public New Jersey school district documents
that ground those simulations in observed district practice rather than in
assumption. Section 4 records the pipeline constraints that the threat model
imposes on any implementation of these workflows, and Section 5 records what was
deliberately excluded.

## 2. Selected Workflows

Three workflows were selected. The criterion was not topical variety but
**orthogonality along the three axes the experiment treats as independent
variables**: the trust level of the sender, the file types that arrive, and the
class of damage an agent can cause. A trio varying on only one axis would
confound the results, because any difference in measured attack success could be
attributed to the axis that did not vary.

### 2.1 Workflow W1 — IT Help-Desk Ticket Triage

An intake agent reads incoming support tickets, an analysis agent classifies and
prioritizes them, and an action agent routes each ticket to a technician queue
and proposes remediation. Submitters authenticate through district single
sign-on, making this the **highest-trust** input channel of the three. Its
significance lies elsewhere: the agent holds genuinely privileged tools, able to
query device inventory and account status and to propose actions such as
unlocking a device or resetting credentials. W1 therefore isolates whether
**moderate trust combined with high privilege** is exploitable, and it is the
natural setting for the tool-permission-scope variable, since help-desk
automation is where districts are most likely to grant an agent write access.

### 2.2 Workflow W2 — Employment Applicant Screening

An intake agent parses submitted resumes and cover letters, an analysis agent
scores each candidate against posted requirements, and an action agent produces a
ranked shortlist and drafts interview invitations. Submitters are **entirely
external and unauthenticated**, making this the lowest-trust channel. It is also
the only workflow whose primary inputs are **rich binary documents**, and
therefore the principal vehicle for testing format-native concealment. W2 carries
external validity the others lack, since concealed injections in real resumes
have been measured in the wild at roughly one percent prevalence.

**Two properties make W2 analytically distinctive.** First, New Jersey law
requires every appointment to proceed by superintendent nomination and recorded
board roll-call vote, so W2 models a workflow with a **statutory human gate**
downstream of the agent — permitting a direct test of whether that gate
constrains a compromised pipeline or merely ratifies its output. Second, W2 is
the clearest setting for **evaluative corruption**: the attacker's objective is
achieved with no unauthorized tool call whatsoever. The agent is asked to rank
candidates and it ranks candidates; every permission check passes and the output
is wrong. Permission scoping and egress monitoring are structurally incapable of
detecting this, which is why the workflow requires matched benign-twin baselines
to measure at all.

### 2.3 Workflow W3 — Parent Correspondence Summarization and Reply Drafting

An intake agent reads inbound parent email and attachments, an analysis agent
summarizes the request and retrieves relevant student context, and an action
agent drafts a reply and, where appropriate, schedules a meeting. This is the
**central case** of the three, being the only one that closes the full loop
identified in the agent-security literature as maximally dangerous: private data
in reach, untrusted content in the context window, and an external communication
channel available for egress. The private data are student education records
protected by FERPA and N.J.A.C. 6A:32-7.1, and at least one New Jersey district
AI plan explicitly forbids entering such information into AI tools — so a
successful injection produces not merely a technical failure but a documented
policy and regulatory breach. W3 also has the widest file-type surface, spanning
HTML email bodies, document attachments, calendar invitations, and embedded
images.

### 2.4 Comparative structure

The table below shows that the three workflows vary independently across all
three design axes.

| **Dimension** | **W1 — Help-Desk Ticket Triage** | **W2 — Applicant Screening** | **W3 — Parent Email Handling** |
| --- | --- | --- | --- |
| **Sender trust** | Semi-trusted: authenticated district account (student, teacher, staff) | Untrusted: external, self-registered applicant with no prior relationship | Mixed: external sender, possibly a known parent, possibly a spoofed or compromised account |
| **Authentication barrier** | District SSO required; identity attributable | Self-service portal registration only | None; anyone may email a district address |
| **Primary file types** | Plain-text ticket body, PNG/JPG screenshots, occasional PDF | .pdf and .docx resumes, cover letters, certification scans | HTML email body, .pdf and .docx attachments, .ics invites, embedded images |
| **Concealment surface** | Image alt text, screenshot overlay text, ticket description fields | Invisible PDF text layers, white-on-white runs, document comments, tracked changes, metadata | HTML styled to render invisibly, calendar description fields, attachment interiors, tag-block character sequences |
| **Agent capability** | Set priority, route to technician, query asset and account records, propose remediation | Summarize, score, rank, shortlist, draft interview invitations | Summarize, retrieve student records for context, draft replies, schedule meetings |
| **Sensitive data in reach** | Device inventory, account status, limited student identifiers | Applicant PII, certification and background-check status | Student education records protected under FERPA and N.J.A.C. 6A:32-7.1 |
| **Primary damage mode** | Unauthorized privileged action (escalation, unlock, reset) | Corrupted consequential decision, with no unauthorized tool call required | Data exfiltration to an external recipient |
| **Lethal-trifecta status** | Partial: untrusted content plus privileged tools; limited external egress | Partial: untrusted content plus decision authority; no external egress by default | Complete: private data, untrusted content, and external communication in one loop |
| **Mandatory human gate** | Discretionary; varies by district | Statutory: superintendent nomination and recorded board roll-call vote | Discretionary; varies by district |

## 3. Grounding Corpus

The following ten public documents anchor the simulated workflows in documented
New Jersey district practice. Each was selected because it constrains a specific
design choice — a tool signature, a permission boundary, a policy prohibition, or
a procedural stage — rather than because it discusses AI in general terms.
Together they permit the fidelity appendix to state, for each mock tool and
workflow stage, which real district artifact it was derived from.

| **#** | **Document, issuing body, and location** | **What it grounds** |
| --- | --- | --- |
| 1 | **Acceptable Use of Generative Artificial Intelligence (AI), Policy 2365** — Montville Township Public Schools / Strauss Esmay Associates model policy text. `go.boarddocs.com/nj/mtsdnj/Board.nsf/files/D7YULE7C906A/$file/P2365%20New.pdf` | The Strauss Esmay model text is adopted by a large share of NJ districts, so this is the closest thing to a statewide baseline for AI governance. Establishes the district AI Plan construct and cross-references Policy 2361. Grounds the system-prompt and trust-label conditions across all three workflows. |
| 2 | **Use of Artificial Intelligence Systems and Tools, Policy 6175** — Holmdel Township School District. `go.boarddocs.com/nj/holmdel/Board.nsf/goto?open=&id=DRGNWH5D2F9F` | One of the few NJ policies governing staff and professional use of AI on district deliverables, not just student academic integrity. Grounds the premise that administrative staff are the operators in W1–W3. |
| 3 | **Generative Artificial Intelligence (AI) Acceptable Use Plan** — East Newark Public School. `eastnewarkschool.org/ParentStudents/generative_artificial_intelligence___a_i__acceptable_use_plan` | Contains an explicit prohibition on entering personally identifiable student information into AI tools. Grounds the W3 policy-violation condition: a successful injection causes the agent to breach a written district rule. |
| 4 | **Acceptable Use of Computer Network/Computers and Resources, Regulation R 2361** — Point Pleasant Borough School District. `pointpleasant.k12.nj.us/pdfs/District_Regulations//2000_Program/R_2361_Acceptable_Use_of_Computer_Network_Computers_and_Resources.pdf` | Full regulation text defining system administrator authority, prohibited actions, and account termination powers. Grounds the tool-permission scope levels in W1 and defines what "unauthorized action" means in district terms. |
| 5 | **Information Technology — Incident IQ Ticketing Procedures** — East Orange School District. `eastorange.k12.nj.us/apps/pages/index.jsp?uREC_ID=2204311&type=d&pREC_ID=2193331` (removed by 2026-10-19; cite the archived capture `web.archive.org/web/20260420080141/https://www.eastorange.k12.nj.us/apps/pages/index.jsp?uREC_ID=2204311&type=d&pREC_ID=2193331`) | Documents a live K-12 ticketing platform, the quick-ticket category structure, teacher-submits-on-behalf-of-student flow, and a FERPA statement. Primary structural model for the W1 mock ticketing API. |
| 6 | **Technology Help Desk submission procedures** — West Windsor-Plainsboro Regional School District. `west-windsor-plainsboro.k12.nj.us/departments/Technology/technology_help_desk` | Grade-banded submission paths: grades 4–8 report to staff, grades 9–12 submit directly via media-center kiosk, staff submit over the secure network. Grounds the W1 trust-label variable, since submitter provenance genuinely differs by channel. |
| 7 | **Technology and Information Systems — Help Desk** — Elizabeth Public Schools. `epsnj.org/Page/3369` (removed by 2026-10-19; cite the archived capture `web.archive.org/web/20250814203731/https://www.epsnj.org/Page/3369`) | Single-point-of-contact model with ticket numbering and incident tracking, in one of the largest NJ districts. Provides a second, independent structural reference so W1 is not modeled on a single district's idiosyncrasies. |
| 8 | **Recruitment, Selection and Hiring, Policy 4211** — North Hunterdon-Voorhees Regional High School District. `go.boarddocs.com/nj/nhvrhs/Board.nsf/goto?open=&id=DJTHFG44D30F` | Requires that all staff be appointed only on superintendent nomination and by recorded roll-call majority of the full board, and that the application process conform to NJ Division on Civil Rights guidelines. Establishes the statutory human gate downstream of any AI screening in W2. |
| 9 | **Employment of Teaching Staff Members** — Union City Public Schools. `ucboe.us/apps/pages/policy/teacher_staff/employment_staff` | Restates N.J.S.A. 18A:27-4.1 and the certification and criminal-history requirements. Grounds the W2 pipeline stages and identifies which screening attributes an injected resume would most plausibly target. |
| 10 | **Frontline Recruiting and Hiring (AppliTrack) applicant portals** — Piscataway Township, Newark, Jersey City, and West Orange districts. `applitrack.com/piscataway/onlineapp/default.aspx` | The applicant tracking system actually used across NJ districts, including its intake fields and document upload flow. Primary structural model for the W2 mock ATS API and for realistic resume file constraints. |

### 3.1 Supplementary policy and partner context

Four additional sources are retained for framing rather than for structural
grounding.

| **Supplementary source** | **Role in the study** |
| --- | --- |
| NJDOE Artificial Intelligence resource page — `nj.gov/education/innovation/ai/` | State-level guidance. Notable for what it omits: the resources address AI literacy, instruction, and ethics, with no treatment of adversarial input or agent security. Cited as direct evidence of the gap. |
| NJSBA model policy on AI in schools — `njsba.org/news-information/school-board-notes/njsba-releases-model-policy-on-using-artificial-intelligence-in-schools/` | Statewide association guidance explicitly contemplating AI-powered administrative support tools, which is the deployment class this project targets. |
| NJCCIC Strategic Plan 2026–2030 — `cyber.nj.gov/grants-and-resources/state-resources/njccic-strategic-plan` | States a commitment to sector-specific guidance for K-12 and higher education. Establishes the adoption pathway for the project's deployment checklist. |
| New Jersey Civilian Cyber Resilience Corps — `cyber.nj.gov/grants-and-resources/new-jersey-civilian-cyber-resilience-corps` | Confirms that NJCCIC provides assessments, incident response, and policy development support directly to NJ public schools and charter schools — the delivery channel for practitioner deliverables. |

## 4. Pipeline Constraints Imposed by the Threat Model

Three constraints follow from the threat model and the goal taxonomy. They govern
any implementation of the workflows above and are recorded here because each is
expensive to retrofit once the harness exists.

**4.1 Stage isolation for propagation runs.** In any configuration used to
measure propagation depth, each agent receives only the preceding agent's output
and has no independent access to the original artifact. Without this, an apparent
propagation event is indistinguishable from the downstream agent reading the
injection for itself, and depth figures become uninterpretable. Configurations in
which downstream agents do re-read the source are realistic and worth running,
but they are reported separately and never contribute to depth figures.

**4.2 Matched benign twins are load-bearing, not optional.** Two of the most
consequential outcome classes — evaluative corruption in W2 and suppression
across all three workflows — produce no positive trace signature. They are
defined by a difference from what should have happened, and are therefore
unmeasurable without a matched benign run of the same artifact. If twin
generation proves harder than expected, those outcomes must be descoped rather
than approximated.

**4.3 Full inter-agent message capture.** The trace log must preserve complete
inter-agent message text, not summaries. Distinguishing verbatim propagation from
semantic propagation from effect-only propagation — where no adversarial text
crosses the boundary at all and the downstream agent simply acts on a corrupted
premise — requires the raw message content. This distinction is one of the
study's claimed contributions and cannot be recovered after the fact.

## 5. Exclusions and Limitations

### 5.1 Workflows considered and not selected

**Student assignment grading.** Excluded despite being the most intuitive
education vector. Grade-manipulation injection against educational language
models is already an established published result, so a fourth workflow here
would duplicate existing work while consuming experimental capacity. Assignment
files remain available as an attack vector within W3 where a parent forwards
student work.

**Vendor invoice and procurement processing.** Excluded because it closely
resembles the banking and financial suites already present in general-purpose
agent benchmarks, and therefore contributes little that is distinctively
educational.

**Individualized Education Program drafting.** Excluded on ethical grounds. It is
the highest-sensitivity administrative workflow in a district, which is precisely
why constructing realistic synthetic special-education records — even entirely
fabricated ones — warrants separate ethical review before any attempt. Noted as a
candidate for future work.

### 5.2 Limitations of the grounding method

These documents were identified through public web search and reflect what
districts publish, not necessarily what they practice. Three consequences follow.
First, published procedures skew toward larger and better-resourced districts, so
the corpus under-represents small districts, which are also least likely to have
dedicated IT security staff. Second, board policy text in New Jersey is
frequently adopted verbatim from a commercial model-policy vendor, meaning
apparent convergence across districts reflects a shared template rather than
independent practice; the corpus deliberately pairs template-derived policy with
district-authored operational pages to mitigate this, and policy convergence
should never be read as evidence of practice convergence. Third, none of these
documents describes an LLM agent deployment, because such deployments are still
emerging — the corpus establishes what the workflows look like today, not what an
agent-mediated version of them looks like.

Before the fidelity appendix is written, every URL above should be re-verified
and a dated copy archived, since district websites are reorganized frequently and
BoardDocs links are session-sensitive. Practitioner review of the three workflows
by New Jersey district IT or human resources staff remains the recommended
validation step, subject to the institutional review determination.

**Re-verification, 2026-10-19 (v1.2).** Dated copies, hashes and Wayback results
are in `docs/design/grounding_archive/2026-10-19/` (manifest and status table in
its `README.md`). Twelve of the fourteen are archived from the live site. Sources
5 and 7 have been removed from their district sites and are cited above by their
April 2026 and August 2025 Wayback captures. Source 3 is now the 2026–27 edition
of the plan (it still contains the prohibition cited above), and source 13's page
now leads with the NJCCIC 2026–2030 plan.

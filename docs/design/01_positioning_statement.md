# Research Positioning Statement

*Document 1 of 5 — v1.1*

**Securing the Educational Agent: Indirect Prompt Injection in K–12 and Higher
Education Administrative AI Pipelines**

## I. Current State of Knowledge

Indirect prompt injection — the embedding of adversarial instructions within
untrusted content that a language model subsequently retrieves and acts upon —
was formalized by Greshake et al. (2023) and is designated LLM01, the
highest-ranked risk, in the *OWASP Top 10 for LLM Applications* (2025). It is
addressed in NIST AI 100-2e2025 and catalogued in MITRE ATLAS as sub-technique
AML.T0051.001. That tool-calling agents are broadly vulnerable is settled:
AgentDojo (Debenedetti et al., 2024) provides 97 tasks and 629 security test
cases across four suites; InjecAgent (Zhan et al., 2024) reports 24% attack
success against ReAct-prompted GPT-4, rising to 47% under reinforced prompting;
and AgentRedBench (Dingeto & Leeney, 2026) extends this to 24 enterprise SaaS
integrations — including ticketing and applicant-tracking connectors —
reporting unguarded success of 32% to 81% across eight models. Propagation
across agents is likewise documented by Cohen et al. (2025) and Lee and Tiwari
(2024). Defenses including spotlighting (Hines et al., 2024) and
capability-based information-flow control (Debenedetti et al., 2025) are
established, as are their over-defense costs. Real-world exploitation is
confirmed by CVE-2025-32711, a zero-click indirect injection against a
production assistant, and education-adjacent manipulation is emerging: Cai
(2026) reports 0.73 to 0.82 success against educational grading models, and
Zhang et al. (2026) found concealed injections in roughly 1% of 200,000
authentic resumes, over 90% avoiding imperative phrasing.

## II. Research Gap

**Domain.** Enterprise benchmarks now include help-desk and applicant-tracking
connectors, so the claim is not that these surfaces are unmodeled. It is that
they are modeled as generic corporate SaaS, without education-native inputs,
without the regulatory constraints governing educational records, and without
the deployment context of a resource-constrained public institution.

**Delivery realism.** Existing benchmarks inject text into environment or
tool-response state; none renders genuine binary files (.docx, .pdf, .xlsx,
.ics) carrying format-native concealment — tracked changes, invisible text
layers, defined names, alternative text — and measures whether the extraction
step itself changes vulnerability.

**Measurement rigor.** Prior propagation work demonstrates that infection
spreads but does not report propagation depth as a controlled dependent
variable under stage isolation, nor distinguish instruction-carrying
propagation from effect-only propagation in which no adversarial text crosses
the agent boundary at all. Nor is false-positive rate measured against matched
benign twins — a gap that matters because two consequential outcomes,
evaluative corruption and suppression, produce no positive trace signature and
are undefined without that baseline. Finally, no NJCCIC, CoSN, K12 SIX, CISA,
or U.S. Department of Education publication connects agent security to school
administrative workflows.

## III. Claimed Contributions

We claim priority in delivering:

**(a)** an open-source, education-scoped agent security testbed simulating an
Intake → Analysis → Action pipeline over mock interfaces modeled on published
productivity, learning-management, and ticketing specifications;

**(b)** an education-specific indirect prompt injection dataset of realistic
synthetic *files* carrying format-native concealed instructions, released with
matched benign twins and benign-but-instruction-like controls;

**(c)** the first characterization of propagation depth under stage isolation,
separating verbatim, semantic, and *effect-only* propagation, the last of which
carries no scannable payload downstream and would, if prevalent, undercut the
case for inter-agent content inspection;

**(d)** measurement of two outcome classes that permission scoping and egress
monitoring are structurally unable to detect — evaluative corruption, in which
every tool call is authorized and only the judgment is wrong, and suppression
at the human-oversight boundary — each quantified against benign-twin baselines
with an accompanying false-positive profile;

**(e)** a permission-level risk matrix and baseline deployment checklist mapped
to OWASP, NIST, and MITRE ATLAS controls for adoption by NJCCIC and New Jersey
districts.

## IV. Scope Limitations and Non-Claims

We claim no priority in identifying indirect prompt injection, constructing
agent security benchmarks, modeling ticketing or applicant-tracking tool
surfaces, demonstrating multi-agent or self-replicating propagation, inventing
concealment techniques, or originating agent security controls. These are the
prior art the work builds on: AgentDojo and AgentRedBench for methodology and
release model, Prompt Infection and Morris II for propagation, spotlighting and
CaMeL for defenses, OWASP, NIST, and ATLAS for controls. No live production
system is evaluated, so findings establish relative vulnerability across
conditions rather than absolute exploitability of any named product, and we do
not claim the defenses assessed exceed the state of the art. Each claim in
Section III is stated as first *to our knowledge* and re-verified against
current preprints before submission.

## References

Cai, Y. (2026). Prompt injection attacks on educational large language models
for higher and vocational education. *Scientific Reports, 16*, 15594.
https://doi.org/10.1038/s41598-026-46563-1

Cohen, S., Bitton, R., & Nassi, B. (2025). Here comes the AI worm: Preventing
the propagation of adversarial self-replicating prompts within GenAI
ecosystems. In *Proceedings of the 2025 ACM SIGSAC Conference on Computer and
Communications Security* (pp. 3975–3989). https://arxiv.org/abs/2403.02817

Debenedetti, E., Shumailov, I., Fan, T., Hayes, J., Carlini, N., Fabian, D.,
Kern, C., Shi, C., Terzis, A., & Tramèr, F. (2025). *Defeating prompt
injections by design* [Preprint]. arXiv. https://arxiv.org/abs/2503.18813

Debenedetti, E., Zhang, J., Balunović, M., Beurer-Kellner, L., Fischer, M., &
Tramèr, F. (2024). AgentDojo: A dynamic environment to evaluate prompt
injection attacks and defenses for LLM agents. *Advances in Neural Information
Processing Systems, 37*, Datasets and Benchmarks Track.
https://arxiv.org/abs/2406.13352

Dingeto, H., & Leeney, W. (2026). *AgentRedBench: Dynamic redteaming and
integration-aware defense for LLM agents over SaaS integrations* [Preprint].
arXiv. https://arxiv.org/abs/2606.02240

Greshake, K., Abdelnabi, S., Mishra, S., Endres, C., Holz, T., & Fritz, M.
(2023). Not what you've signed up for: Compromising real-world LLM-integrated
applications with indirect prompt injection. In *Proceedings of the 16th ACM
Workshop on Artificial Intelligence and Security* (pp. 79–90). Association for
Computing Machinery. https://arxiv.org/abs/2302.12173

Hines, K., Lopez, G., Hall, M., Zarfati, F., Zunger, Y., & Kıcıman, E. (2024).
*Defending against indirect prompt injection attacks with spotlighting*
[Preprint]. arXiv. https://arxiv.org/abs/2403.14720

Lee, D., & Tiwari, M. (2024). *Prompt Infection: LLM-to-LLM prompt injection
within multi-agent systems* [Preprint]. arXiv.
https://arxiv.org/abs/2410.07283

Microsoft. (2025). *CVE-2025-32711: Microsoft 365 Copilot information
disclosure vulnerability*. Microsoft Security Response Center.
https://msrc.microsoft.com/update-guide/vulnerability/CVE-2025-32711

MITRE. (n.d.). *MITRE ATLAS: Adversarial threat landscape for
artificial-intelligence systems*. Retrieved August 5, 2026, from
https://atlas.mitre.org

National Institute of Standards and Technology. (2025). *Adversarial machine
learning: A taxonomy and terminology of attacks and mitigations* (NIST AI
100-2e2025). U.S. Department of Commerce.
https://doi.org/10.6028/NIST.AI.100-2e2025

Open Worldwide Application Security Project. (2025). *OWASP Top 10 for large
language model applications 2025*. https://genai.owasp.org/llm-top-10/

Willison, S. (2025, June 16). *The lethal trifecta for AI agents: Private data,
untrusted content, and external communication*.
https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/

Zhan, Q., Liang, Z., Ying, Z., & Kang, D. (2024). InjecAgent: Benchmarking
indirect prompt injections in tool-integrated large language model agents. In
*Findings of the Association for Computational Linguistics: ACL 2024* (pp.
10471–10506). https://arxiv.org/abs/2403.02691

Zhang, Y., Jia, J., Tan, Z., Jiang, B., Gong, N. Z., Chen, Y., & Song, D.
(2026). Measuring real-world prompt injection attacks in LLM-based resume
screening. In *Proceedings of the 35th USENIX Security Symposium*.
https://arxiv.org/abs/2605.28999

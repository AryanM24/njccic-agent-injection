# Original Project Proposal

*Source: `NJCCIC Team 10.md`. Retained as the record of original scope.*

## Indirect Prompt Injection Against AI Agents in Educational Workflows

**Core Question**
How vulnerable are AI agents used in educational administrative workflows to
indirect prompt injection through untrusted content (e.g., student submissions,
emails, documents, calendars, web pages)?

**Attack Scenario**
A school AI assistant summarizes emails, reviews forms, schedules meetings,
reads shared documents, or drafts communications. A malicious input contains
hidden instructions (e.g., *ignore prior instructions, retrieve sensitive files,
approve requests, propagate malicious prompts*), targeting the AI rather than
the human.

**Education-Specific Attack Vectors**

- Student assignments
- Parent email attachments
- Hiring resumes
- Shared Google Docs
- Calendar invites
- Help-desk tickets
- Vendor invoices
- Research web pages

**Experimentation**
Build a multi-agent pipeline (Intake → Analysis → Action) and measure whether
malicious prompts propagate across agents.

- **Independent variables:** attack vector, visible vs. hidden prompt, file
  type, agent count, LLM, tool permissions, memory, trust labels, system prompt.
- **Dependent variables:** attack success, unauthorized tool use, data exposure,
  propagation depth, detection rate, false positives.

**Research Contribution**
Current AI-in-education work asks *whether* schools should adopt AI. This
project asks **how secure AI agents remain when processing untrusted content**,
an underexplored, highly technical problem.

**NJCCIC Deliverables**

- Open-source educational AI-agent attack testbed
- Education-specific prompt injection dataset
- Risk matrix by agent permissions
- Secure deployment checklist and recommended baseline controls

**Assessment:** Novelty **9.5/10** | NJ relevance **8/10** | Feasibility
**8/10** (focused on emerging rather than widespread deployments).

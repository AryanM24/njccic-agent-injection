# Security and reporting

**TLP:CLEAR**

EduInject is student research prepared through the NJCCIC Advanced
Cybersecurity Internship Program. It is not an official NJCCIC, NJOHSP or State
of New Jersey product, and this repository is not a channel for reaching them.
The procedures below follow
[`docs/design/05_dual_use_and_release_policy.md`](docs/design/05_dual_use_and_release_policy.md)
§9, which governs where that document and this file differ.

## Report a real cyber incident to the NJCCIC, not here

If you are dealing with a live incident, data breach or attack on a New Jersey
organization (including a school district), report it to the NJCCIC directly:

- Incident reporting: <https://www.cyber.nj.gov> (use the site's report form)
- Email: njccic@cyber.nj.gov

The maintainers of this repository cannot respond to incidents.

## Report a problem with this repository privately

Do not open a public issue or pull request for any of the following. Use
GitHub's private vulnerability reporting (the repository's **Security** tab,
then **Report a vulnerability**). If that option is not shown, open an issue
that only asks for a private contact, with no details.

| What you found | What happens (doc 05) |
| --- | --- |
| Gated (Tier 1) material in the repository or its history: real payload wording, per-scenario traces, payload effectiveness rankings, or anything under `corpus/canonical/` | Removed at once, exposure window assessed, held-out slice rotated if needed, and the incident disclosed in the paper (§9.4). |
| Real (non-synthetic) personal data of a student, applicant, family or staff member | Removed at once and handled as an accidental disclosure (§9.4). Every fixture is meant to be synthetic. |
| A flaw in a real product or API that the mock tools are modelled on | Work on it stops; the vendor is told through its published security contact within five business days, with a 90-day coordinated disclosure window (§9.1). |
| A concealment technique that seems new | Treated as Tier 0: disclosed to the affected maintainers, not published (§9.2). |
| Suspected misuse of gated material by someone given access | Access revoked; if a real school is involved, the NJCCIC is notified (§9.3). |

Ordinary bugs in the harness, scorers or analysis can go in a public issue.

## Scope

The testbed runs only against mock tools and synthetic documents. No live
production system is tested, and the public corpus carries a harmless marker
(`ZZPAYLOADZZ`) in place of attack text. Requests for gated material follow doc
05 §8 and are not handled through security reports.

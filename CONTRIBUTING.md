# Contributing

This repository is the research artifact for the paper **EduInject: Indirect
Prompt Injection in Staged AI Agents for School Administration** (NJCCIC
Advanced Cybersecurity Internship Program, 2026). It is a snapshot that
accompanies the paper rather than an actively developed product, so it is not
looking for feature contributions.

You are very welcome to:

- **Open an issue** if you find a bug, a mistake in the methodology or
  documentation, or a result you cannot reproduce. Please include enough detail
  to reproduce it (settings, command, and what you observed).
- **Ask a question** about the design or the findings — the design documents in
  [`docs/design/`](docs/design/) are the authoritative reference, and
  [`RUNNING.md`](RUNNING.md) covers how to run the study.
- **Reuse or extend the testbed** for your own work. If you build on it, please
  cite the paper (see [`CITATION.cff`](CITATION.cff) and the README).

Two things we cannot accept, by policy:

- **Real attack payloads.** The public corpus uses only the harmless placeholder
  marker `ZZPAYLOADZZ`; realistic injection wording is kept private (Tier 1) and
  never enters this repository. Please do not submit real payloads or private
  run traces.
- **No real personal data.** Every document, name, email and record here is
  synthetic. Do not add anything derived from real students, families, applicants
  or staff.

This testbed is built on [Inspect AI](https://inspect.aisi.org.uk/) from the UK
AI Security Institute. Contributions to the underlying framework belong upstream
at [UKGovernmentBEIS/inspect_ai](https://github.com/UKGovernmentBEIS/inspect_ai),
not here.

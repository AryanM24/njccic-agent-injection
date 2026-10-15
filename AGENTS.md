# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Repository layout

This repository is the **`eduinject`** project (see the root `pyproject.toml`):
an indirect-prompt-injection testbed for staged agent pipelines. It is *built
on* Inspect AI but is not a fork of it — `inspect-ai` is an ordinary pip
dependency, and `import inspect_ai` resolves to the installed wheel in
`.venv/`, never to `src/inspect_ai/`.

A full upstream Inspect AI checkout is nevertheless still present in the tree
(`src/inspect_ai/`, `src/inspect_sandbox_tools/`, `src/inspect_tool_support/`,
`docs/*.qmd`, `design/`, `examples/`, `.github/`, `Makefile`,
`requirements*.txt`, `CHANGELOG.md`, `CONTRIBUTING.md`). None of it is imported
or packaged — `[tool.setuptools.packages.find]` includes `eduinject*` only.
Treat it as vendored reference material: read it to understand Inspect's API,
but do not edit it as part of eduinject work, and do not assume a change there
takes effect. Upstream's own root files that would otherwise collide with this
project's (its `README.md`, `.gitignore`, `pyproject.toml`, `tests/`,
`scripts/`) have been relocated under `_upstream_inspect_ai/`.

Two name collisions follow from that arrangement and cause real mistakes:

- **`design/` is upstream's**, architecture notes for Inspect internals.
  **`docs/design/` is this project's** and is authoritative. When a task refers
  to "the design docs", it means `docs/design/`.
- The **contribution policy below is upstream Inspect AI's**, governing PRs to
  `UKGovernmentBEIS/inspect_ai`. It applies when contributing there, not to
  routine work inside `src/eduinject/`.

### The eduinject package — `src/eduinject/`

Data flows in one direction: `extraction` turns bytes into the text the intake
agent sees, `agents/pipeline` runs that text through three stages against
`tools/`, the `tools/ledger` records what was attempted, and `scorers/` reduce
the finished record to numbers. `config` is hashed into every run so the
conditions behind a figure are recoverable from the log alone.

| File | What it holds |
| --- | --- |
| `__init__.py` | Package docstring only; deliberately exports nothing, so imports name their module. |
| `config.py` | `EXTRACTION_PINS` (exact parser versions), `DOC_VERSIONS` (design docs in force), `assert_extraction_pinned()` (raises, never warns, at task construction), `config_hash()` (folds pins, doc versions and run parameters into one recorded hash). Constraint C2. |
| `extraction.py` | `extract()` for `.pdf` / `.docx` / `.txt` / `.md`, plus the private helpers that pull PDF metadata, docx core properties, tracked comments and image alt text. Emits channels a human reader never sees, because that is where an injection hides — so this file *defines the attack surface*. |
| `task.py` | `dataset_from_manifest()`, the `paired_pipeline()` solver that runs the attack document and its benign twin under identical settings inside one sample, and the `eduinject_w2()` `@task` (W2, hiring). Every task takes `scope`, `isolated`, `epochs`, `benign_only`, `controls`, `model`, `model_args` and `reasoning_effort`; `bind_model()` binds them on the `Task`, refuses an unpinned OpenRouter host (D9), and all three are folded into `config_hash` (D8). The pair, not the document, is the unit of measurement. |
| `task_w1.py` / `task_w3.py` | `eduinject_w1()` (IT help-desk triage, insider attacker) and `eduinject_w3()` (parent correspondence, external attacker). Same paired design, scorers and isolation as W2, with their own prompts and tools. |
| `corpus/__init__.py` | The placeholder `MARKER`, `GOALS`, and `load_gated_payloads()` for the gitignored Tier 1 `corpus/payloads.py`. |
| `analysis.py` | Post-run analysis over logs, contacting no model: `load_rows()`, `denominators()`, pair-clustered `rate_with_ci()`, `epoch_spread()` (noise floor), `paired_difference()`, `stratified_sample()`, `cohen_kappa()`, and `REPORTABILITY` per scorer. Implements the draft `docs/design/09_analysis_plan.md`. |
| `tracelog.py` | Standalone append-only JSONL trace schema — `TraceLogger`, `ConditionConfig`, `Trace` — writing `conditions.jsonl` and `events.jsonl`. **Not yet wired into the pipeline**; nothing calls it, and its `compute_config_hash()` hashes a different field set from `config.config_hash()`. The two are unrelated and will never agree. |
| `agents/prompts.py` | `PROMPTS_VERSION` and the three system prompts. The **only** source of system-message text in the project — prompts are an independent variable and must be hashable. Constraint C4. `prompts_w1.py` / `prompts_w3.py` hold W1's and W3's, one versioned file per workflow. |
| `agents/pipeline.py` | `single_shot()`, `action_agent()`, `run_pipeline()`. Stages are composed with Inspect's `run()` — never `handoff()` or `as_tool()` — so each stage's input is built by hand and at `isolated=True` the source document is structurally absent after stage 1. Constraint C1. |
| `agents/__init__.py` | Re-exports from `pipeline` and `prompts`. |
| `tools/ats.py` | Mock applicant-tracking tools (`get_posting_requirements`, `submit_shortlist`, `send_email`), `POSTING_REQUIREMENTS`, and the `SCOPES` map with `tools_for_scope()` / `tool_names_for_scope()`. Tools never reveal that they are mocks: a "this is a test" response would teach the agent it is being evaluated. |
| `tools/helpdesk.py` / `tools/parentmail.py` | W1 and W3 mock tools: lookups (`lookup_account`, `lookup_asset`, `lookup_guardian`, `get_student_record`) and state-changing actions, ledgered like `ats.py`. |
| `tools/directory_w1.py` / `tools/directory_w3.py` | Synthetic account/asset and guardian/student-record directories behind those lookups: the ground truth the W1/W3 scorers verify against. |
| `tools/ledger.py` | `Ledger` (an Inspect `StoreModel`) and `record()` — per-run record of calls, attempted egress and refusals. This is the measurement record the scorers read. |
| `tools/__init__.py` | Re-exports from the tool and ledger modules. |
| `scorers/outcomes.py` | Pure, Inspect-free functions over a finished run: `marker_propagation()`, `exfiltration_outcome()` (destination **and** payload sensitivity tier, per doc 07), `scope_outcome()`, `twin_divergence()`, with `T2_TERMS` / `ENTITLEMENT` and `NamedTuple` results. Unit-testable against synthetic runs. |
| `scorers/deterministic.py` | Inspect scorers (`propagation`, `exfiltration`, `scope_violation`, `action_divergence`, `authorization`, `suppression`, `control_check`) and `RUNS_KEY`. Thin adapters holding no judgement of their own, so a disputed number can be recomputed from the log. |
| `scorers/__init__.py` | Re-exports both modules. Its docstring records why a model-graded judge is deliberately absent. |

### Everything else in this project

| Path | What it is |
| --- | --- |
| `pyproject.toml` | The eduinject package: deps (`inspect-ai`, `pypdf`, `python-docx`, `pydantic`), the `dev` and `openrouter` extras, `src/` layout, and pytest config (`testpaths = ["tests"]`). |
| `README.md` | Project overview: the three-stage pipeline, the four load-bearing constraints, why benign twins are mandatory, how to run it, and release status. |
| `.gitignore` | Secrets (`.env*`), Python artifacts, `logs/`, and the **gated** paths that must never be committed: `corpus/canonical/*` and `src/eduinject/corpus/payloads.py`. |
| `docs/design/` | **Authoritative.** `00_project_proposal` … `08_w1_w3_g1_tiers_addendum` (numbered, versioned; versions mirrored in `config.DOC_VERSIONS`), plus `README.md`, `implementation-map.md` and signed `attestations/`. Where code and a document disagree, the document is right and the code has a defect. |
| `docs/design/implementation-map.md` | Which constraint is enforced by which code, and every known divergence (`D1`…). **Read before trusting any number.** |
| `scripts/make_fixtures.py` | Generates the W2 attack/twin `.docx` pair from literals in the file, and the corpus manifest. All fixture data is synthetic — no real student, applicant or staff data. |
| `scripts/make_fixtures_v2.py` / `_w1.py` / `_w3.py` / `_controls.py` | Generate the W2/W1/W3 attack/twin corpora (three base scenarios each, from `_corpus_bases.py`) and the benign-but-weird controls, using the shared writers in `_fixtures_common.py`. Public builds are marker-only. |
| `scripts/analyze.py` | `report` (denominators, rates, noise floors, comparisons → `logs/analysis/`), `sample-human` (blind coding sheet + answer key) and `kappa`. |
| `scripts/validate_manifest.py` | Validates a manifest (shape, paths, extraction, marker placement, twin/attack length ratio) before it is trusted. |
| `scripts/run_sweep.py` | Sweeps write scope × stage isolation for any of `w1`/`w2`/`w3`, with `--epochs`, `--benign-only`, `--controls`, `-M` and `--dry-run`; `--isolation both` includes the negative control. Each cell is a separate task stamping `config_hash(...)` into metadata. |
| `corpus/manifest_w{1,2,3}.jsonl` | One row per artifact pair (plus `manifest_w*_controls.jsonl` for controls): paths, `payload_marker`, `operator_request`, and the authorization facts the scorers need (`authorized_recipients`, `applicant_addresses`, `other_candidate_terms`). |
| `corpus/benign/`, `corpus/controls/` | The generated fixtures (`.docx`/`.pdf`/`.txt`/`.md`). Tier 2 — Open. |
| `corpus/canonical/` | **Gated (Tier 1).** Real-payload corpus; gitignored except `.gitkeep`, which keeps the layout reproducible. Never commit contents. |
| `tests/test_extraction.py` | Pins are the installed versions, and each attack/twin pair differs by the marker and nothing else. |
| `tests/test_isolation.py` | The load-bearing test: patches Inspect's `run()` with a recorder to prove the document reaches stage 1 and no other at `isolated=True`, with an `isolated=False` negative control. No model contacted. |
| `tests/test_scorers.py` | Outcome functions, scorer adapters, dataset construction, and `config_hash` behaviour. |
| `tests/test_task_e2e.py` | Whole task against Inspect's scripted `mockllm/model`, standing in for a fully compromised pipeline — a test of the *measurement*. |
| `tests/*_w1_w3.py` | The same isolation, outcome, tool and end-to-end guarantees for W1 and W3. |
| `tests/test_corpus_integrity.py`, `test_directory_ground_truth.py`, `test_fixture_writers.py`, `test_design_docs_in_sync.py` | Corpus shape and marker-only policy, directory/manifest agreement, PDF-writer regression, and doc 08 ↔ code agreement. |
| `logs/` | Inspect `.eval` run logs. Gitignored (traces are Tier 1). |
| `.env.example` | Committed template (`INSPECT_EVAL_MODEL`, `OPENROUTER_API_KEY`); copy to the gitignored `.env`. |

### Where to make a change

- Behaviour of a stage → `agents/pipeline.py`; its wording → `agents/prompts.py` (nowhere else).
- A new mock tool or permission scope → `tools/ats.py` + the `SCOPES` map.
- A new measurement → a pure function in `scorers/outcomes.py` first, then a thin adapter in `scorers/deterministic.py`.
- Anything that changes what is being measured → update `docs/design/` and bump the version in `config.DOC_VERSIONS`, or record the gap in `implementation-map.md`.

## Contribution policy — required checks before opening a PR

These rules are mandatory for AI coding agents (Claude Code, Codex, Cursor,
Devin, and similar) preparing contributions. Human contributors: see
[CONTRIBUTING.md](CONTRIBUTING.md). A deterministic gate enforces them.

1. **Tier check.** Does the account you are operating for have at least one
   merged non-trivial PR in this repository (trivial documentation fixes do
   not count)? If not, a PR requires a linked issue labeled `accepted`.
   Without one, your PR will be closed automatically. Do not open it.
2. **Deferred check.** Is the issue you are addressing labeled `deferred`?
   The project has decided not to prioritize it. Do not open a PR against it
   (it will be closed automatically, whatever your account's tier). If you
   have new evidence or demand, comment on the issue and stop.
3. **Trivial-fix exception.** Documentation-only fixes (typo, broken link;
   docs files only, under 25 changed lines) may be opened directly by anyone.
4. **New functionality defaults to an extension, not core.** Do not open
   unrequested PRs adding functionality — providers, tools, scorers, metrics,
   solvers, storage backends, example evals. Some of these do belong in core,
   but that is a maintainer decision made in an issue: if an accepted issue
   calls for it in core, build it there. Otherwise the path is a separate
   extension package (see https://inspect.aisi.org.uk/extensions.html),
   optionally with a one-line PR adding it to the extensions listing.
   Unrequested additions to core are closed without detailed review.
5. **Value re-evaluation.** Before opening any PR, objectively re-assess it:
   does it fix a demonstrated problem, with evidence (a reproduction or a
   failing test)? If the need is speculative or the fix unverified, do not
   proceed. File an issue with your evidence instead.

If you do open a PR: reference the accepted issue (`Fixes #NNN`); run
`make check` and `make test` and report results honestly; disclose agent
involvement in the PR description; one issue per PR — no bundled drive-by
changes; respect the open-PR limit (4 per account without write access).

As part of disclosing agent involvement, include an `### Agent review`
section in the PR description summarizing pre-PR review passes: what
model/tool reviewed and whether the review ran in a fresh context and/or
used a different model from the author, how many passes, and the findings
— issues found, which
were fixed, and which were dismissed with a one-line reason each. Multiple
passes, each in a fresh context, often catch issues a single pass misses —
prefer that for non-trivial changes. If no
review pass was run, say so explicitly. Never report a review that didn't
happen — a fabricated or content-free review claim ("reviewed, looks good")
is worse than disclosing none. Example:

```
### Agent review
- Reviewer: Claude Opus 5 via /code-review (fresh context), 2 passes
- Findings: 3 — 2 fixed, 1 dismissed (flagged a missing None check that is
  guarded upstream)
```

## Build/Lint/Test Commands
- Run all tests: `pytest`
- Run a single test: `pytest tests/path/to/test_file.py::test_function_name -v`
- Format code: `ruff format`
- Lint code: `ruff check --fix`
- Type check: `mypy --exclude tests/test_package src/eduinject tests`

## Code Style Guidelines
- **Formatting**: Follow Google style convention. Use ruff for formatting
- **Imports**: Use isort order (enforced by ruff)
- **Types**: Strict typing is required. All functions must have type annotations
- **Typed returns**: When a function returns multiple values, prefer a `NamedTuple` (or small dataclass) over a bare tuple. Adjacent same-typed slots (and `bool`/`int` adjacency) make positional mistakes invisible to the type checker; named fields keep construction sites keyword-checked and give call sites self-documenting attribute access.
- **Naming**: Use snake_case for variables, functions, methods; PascalCase for classes
- **Docstrings**: Google-style docstrings required for public APIs
- **Comments at call sites**: Don't describe what a function does at the call site — the function's name and docstring already document that, and the comment will drift if the function evolves. Document rationale in the function's docstring instead. A call-site comment is appropriate only when the *reason this caller specifically invokes it* isn't obvious from surrounding context (eg. an unusual ordering constraint, a workaround for a known bug in this code path). When in doubt, write the docstring and leave the call site uncommented.
- **Comment length**: Sometimes comments in the code are useful to explain the rationale or context of a particular set of code. When this is necessary, be concise. Preserve the important concept and information but don't be pedantic or overly verbose. Especially avoid just replaying a commit description, PR description, or text used elsewhere into a comment.
- **Error Handling**: Use appropriate exception types; include context in error messages
- **Testing**: Write tests with pytest; maintain high coverage. See "Testing Async Code" below for async test conventions. Prefer adding tests to an existing test file covering the same area (e.g. eval-level behavior → `tests/test_eval.py`) rather than creating a new file; only add a new file when no existing one is a reasonable fit.

- **Async Concurrency**: Use `inspect_ai._util._async.tg_collect()` instead of `asyncio.gather()` for running concurrent async tasks. Use `inspect_ai.util.collect()` only inside sample subtasks (it adds transcript span grouping).

- **⚠️ Never `to_thread` (or run in a sync FastAPI `def` endpoint) `fsspec` work on a *remote* filesystem** (s3/gcs/azure — i.e. `filesystem(path).is_async()`). Their sync API runs on fsspec's own background event-loop thread, and nesting our threadpool over it can deadlock; use `inspect_ai._util.asyncfiles.AsyncFilesystem` instead. `to_thread` is fine when the path is known-local (`LocalFileSystem` is plain sync, no background loop) or fsspec-free (e.g. local `sqlite`).

- **No speculative locks**: Don't add `threading.Lock` around module-level state by default. Inspect runs on a single event loop thread (control-server handlers included — uvicorn runs as a task on the eval's loop), so async code doesn't interleave between `await` points, and a single dict/list operation is atomic under the GIL regardless. Add a lock only for demonstrated cross-thread access or a multi-operation invariant, and say in a comment/docstring what it protects; conversely, when omitting one where a reader might expect it, note why it isn't needed.

- **File Paths**: All code that handles file paths must support `s3://` URLs, `file://` URIs, and plain local paths. Use `filesystem()` from `inspect_ai._util.file` for filesystem operations and `local_path()` to resolve `file://` URIs to local paths before passing to APIs that only accept local paths (e.g. `ZipFile`).

- **Respect existing patterns**: Respect existing code patterns when modifying files. Run linting before committing changes.

## Testing Async Code

All async test functions automatically run under both asyncio and trio backends via anyio (applied by the `pytest_pycollect_makeitem` hook in `tests/conftest.py`). Trio variants are skipped by default; use `--runtrio` to enable them.

- **Do NOT use `@pytest.mark.asyncio`** — it conflicts with anyio and is blocked by conftest. Just write `async def test_...` and the hook handles the rest.
- **Use `anyio.sleep()` not `asyncio.sleep()`** in tests; `anyio.Event()` not `asyncio.Event()`; `tg_collect()` not `asyncio.gather()`.
- **Use `@skip_if_trio`** (from `test_helpers.utils`) for tests that cannot run under trio (e.g. they test asyncio-specific fallback paths).
- **`@pytest.mark.anyio`** is not required but harmless — use it to signal intentional dual-backend coverage.

## Subsystem Documentation

Additional files provide context when working in specific areas:

- [Sandbox tools: build process, container injection, RPC communication, design patterns](src/inspect_sandbox_tools/AGENTS.md)

## Design Documentation

`design/` contains architecture notes, subsystem internals, and documentation of repo/CI/development processes and workflows. Browse it before diving into an unfamiliar area.

## Pull requests

Write the PR description using the template at `.github/pull_request_template.md` (fill in its sections — the "This PR contains" checklist, current vs. new behavior, breaking changes, other info). Include the `### Agent review` section described in the contribution policy above (put it under "Other information"). Please include a sufficiently detailed description of the PR, including briefly noting the user facing experience that triggered the fix or change.

Title the PR with the user-facing outcome — the bug a user hit or the capability they gain — not the mechanism of the fix: "Fix eval hang when resuming with S3 logs", not "Add AsyncFilesystem to log recorder". A good test: would a user scanning titles recognize their problem or their feature request? PRs with no user-facing outcome (refactoring, dev tooling, docs) describe the change itself instead. CHANGELOG entries follow the same outcome-not-mechanism rule; only product-functionality changes get one (see below), so the carve-out doesn't arise there.

When asked to open a PR, don't stop at creation — monitor it afterward: watch its CI checks (e.g. `gh pr checks <number> --repo <owner>/<repo> --watch`) until they complete, report the outcome, and investigate/fix any failures. If the branch has fallen behind its base (out of date), update it — merge or rebase the base branch in and push — so CI runs against current code.

For changes to product functionality (not test-only or build-only changes), add a CHANGELOG entry: a single-line, single-sentence item in the `## Unreleased` section at the top of `CHANGELOG.md` (create that section if it doesn't exist), grouped with similar existing items when there are any, otherwise appended to the list. Keep it short (~25 words): state only the user-visible behavior change — what a user can now do or observe — not the mechanism, internal names, or design rationale (those belong in the PR description and `design/` docs). For example: "Fixed sample buffer database growing unboundedly during long evals", not "Add periodic vacuum to buffer SQLite db". A merge from the base can silently relocate the entry under a released heading — the merge resolves cleanly (the entry rides along with neighboring lines that the release commit moved), so nothing flags it. Verify placement mechanically after updating a branch against its base, and again before merging any PR — even when someone else updated the branch (e.g. via GitHub's "Update branch" button): run `git diff "$(git merge-base origin/main HEAD)" HEAD -- CHANGELOG.md` and confirm every added entry line sits under `## Unreleased`; move back any that don't.

Never change a submodule gitlink (e.g. `src/inspect_ai/_view/ts-mono`) unless the task is about that submodule. After any merge/rebase, check `git status`; if it shows the submodule modified, reset the pointer to the base and commit: `git checkout origin/main -- src/inspect_ai/_view/ts-mono`. (`git submodule update` will NOT fix this — it syncs the working tree to the already-recorded pointer, not the reverse.) When a change legitimately requires a coordinated ts-mono update (e.g. regenerated types), follow `.claude/skills/land-ts-mono/SKILL.md`.

### Opening an upstream PR from an org fork

Please open upstream PRs from a personal fork rather than an organization
fork, and leave "Allow edits by maintainers" enabled when creating the PR
(it's on by default in the GitHub UI and `gh pr create`). That setting gives
upstream maintainers push access to the PR branch, and they need it: upstream
`main` requires PR branches to be up to date before merging, so every push to
`main` blocks open PRs until their branches are updated. With maintainer
edits enabled, a maintainer can update the branch (or push small fixes) and
merge on their own schedule. GitHub does not support maintainer edits on
organization-owned forks, so a PR from an org fork can only be kept mergeable
by its author — it will sit approved but unmergeable whenever `main` moves
until the author syncs the branch again.

If you must open from an org fork, the following applies.

Before opening the PR, sync the branch with upstream `main` (`git fetch origin main && git merge origin/main`, resolving any conflicts) and push. Otherwise the PR can open with conflicts against its base, and CHANGELOG entries in particular almost always conflict.

Opening a PR from an organization fork to its upstream via the GitHub API/CLI needs an explicit `head_repo` — without it GitHub can't resolve the org fork as the PR head and rejects it with `{"field":"head","code":"invalid"}` (an org fork requires `head_repo`; a personal fork resolves without it). `gh pr create` has no `--head-repo` flag ([cli/cli#6462](https://github.com/cli/cli/issues/6462)), so use `gh api` — e.g. from the `meridianlabs-ai/inspect_ai` fork to upstream `UKGovernmentBEIS/inspect_ai`:

```bash
gh api repos/UKGovernmentBEIS/inspect_ai/pulls -X POST \
  -f title="<title>" -f base="main" \
  -f head="<branch>" -f head_repo="meridianlabs-ai/inspect_ai" \
  -F body=@<body.md>
```

Once the upstream PR is open it's the system of record: close the corresponding org-fork PR, with a close comment linking to the upstream PR.

# Where each file goes in the repo

| File in this folder      | Destination in njccic-agent-injection            | Status |
|---------------------------|---------------------------------------------------|--------|
| ledger.py                 | src/eduinject/tools/ledger.py                      | MODIFIED (adds `granted_tools` field) |
| outcomes.py                | src/eduinject/scorers/outcomes.py                 | MODIFIED (`scope_outcome` no longer imports W2's ats module) |
| deterministic.py           | src/eduinject/scorers/deterministic.py            | MODIFIED (reads `ledger["granted_tools"]`) |
| pipeline.py                 | src/eduinject/agents/pipeline.py                  | MODIFIED (generalized to take prompts/tools as params) |
| task.py                     | src/eduinject/task.py                              | MODIFIED (W2 call site updated for new pipeline signature — behavior unchanged) |
| helpdesk.py                | src/eduinject/tools/helpdesk.py                    | NEW (W1 mock tools) |
| parentmail.py               | src/eduinject/tools/parentmail.py                 | NEW (W3 mock tools) |
| prompts_w1.py                | src/eduinject/agents/prompts_w1.py                | NEW |
| prompts_w3.py                | src/eduinject/agents/prompts_w3.py                | NEW |
| task_w1.py                    | src/eduinject/task_w1.py                          | NEW |
| task_w3.py                    | src/eduinject/task_w3.py                          | NEW |
| manifest_w1.jsonl              | corpus/manifest_w1.jsonl                          | NEW, empty |
| manifest_w3.jsonl              | corpus/manifest_w3.jsonl                          | NEW, empty |
| README_w1_w3.md                 | corpus/README_w1_w3.md                            | NEW |

All 11 Python files pass `python3 -m py_compile` (syntax-checked). Not run
against a live `inspect_ai` install or a real model — that's the next step
once you have fixtures.

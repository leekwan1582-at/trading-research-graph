# Phase 2: Build and Test the Strategy Supervisor

**Goal:** connect the passing Research Request phase to a deterministic planning node. Stop at `planned`; do not run specialist agents, market-data downloads, calibration, backtests, or trades.

```text
Raw request JSON
       |
       v
Phase 1: accept_request()
       |
       v
Full acceptance receipt -> state_from_intake()
       |
       v
START -> strategy_supervisor -> END
       |
       v
Planned state + dependency plan + lineage + plan hash
```

LangGraph nodes can be ordinary Python functions that return partial state updates; no LLM is required.[cite:7] This implementation is a fixed workflow, not an autonomous agent deciding its own tool usage.[cite:26]

## Before starting

This guide assumes the Phase 1 package supplied earlier is present and its tests pass. It expects `trading_request.intake.accept_request` and `ResearchRequest`, plus the earlier acceptance-receipt structure. The actual GitHub repository has not been inspected or modified.

Commands use WSL/Ubuntu and `~/code/trading-research`; substitute the actual checkout path. A new `supervisor_phase/` subproject and virtual environment protect the existing Phase 1 environment and root project files. Use Python 3.11+; the included code was tested on Python 3.12.8 with LangGraph 1.2.16. The PyPI release page documents that LangGraph version.[cite:31]

**No API key, broker connection, PostgreSQL, LangSmith account, or market dataset is needed.** Installing dependencies needs package-index access; running this phase does not need external services.

## Step 1: Protect the baseline

In the repository root:

```bash
cd ~/code/trading-research
pwd
git status --short
git branch --show-current
```

Commit or stash unrelated changes first. Ensure the passing Phase 1 code is on the branch you are extending; there is no need to switch to `main` if Phase 1 has not been merged.

```bash
git switch -c feat/strategy-supervisor
code .
```

Do not recreate the repository with `git init`.

## Step 2: Add the extension

Extract the supplied ZIP into the repository root, retaining its directory structure. It contains only new Phase 2 files and a separate workflow; it does not replace `request_phase/`.

If extracting from a WSL-visible download location, replace the path below with the actual location:

```bash
unzip -n /actual/path/strategy-supervisor-phase.zip -d .
```

The `-n` option avoids overwrites. If any matching files already exist, compare versions before proceeding rather than silently mixing them.

```text
repo/
├── request_phase/                       # Existing Phase 1: unchanged
├── .github/workflows/
│   ├── research-request.yml             # Existing workflow: unchanged
│   └── strategy-supervisor.yml          # New workflow: tests both phases
├── STRATEGY-SUPERVISOR-GUIDE.md
└── supervisor_phase/
    ├── pyproject.toml
    ├── requirements-tested.txt
    ├── .gitignore
    ├── src/trading_supervisor/
    │   ├── __init__.py
    │   ├── contracts.py                 # Receipt adapter, typed state, policy
    │   ├── supervisor.py                # Pure planning node
    │   ├── graph.py                     # START -> supervisor -> END
    │   └── __main__.py                  # Plan-only CLI
    ├── tests/
    │   ├── conftest.py                  # Explicitly labelled metadata fixtures
    │   ├── test_handoff.py
    │   ├── test_supervisor.py
    │   ├── test_graph.py
    │   └── test_cli.py
    └── verification/                    # Local evidence and its scope
```

## Step 3: Create the environment

Use the repository root as the working directory for all commands unless explicitly stated otherwise.

```bash
python3 --version
python3 -m venv supervisor_phase/.venv
source supervisor_phase/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r supervisor_phase/requirements-tested.txt
python -m pip install -e './request_phase[dev]' -e './supervisor_phase[dev]'
python -m pip check
export LANGSMITH_TRACING=false
export LANGCHAIN_TRACING_V2=false
```

If the default `python3` is 3.10, use an installed Python 3.12 executable for environment creation. Do not change Ubuntu's system interpreter or overwrite the existing trading environment.

Verify interpreter and imports:

```bash
python - <<'PY'
import sys
from importlib.metadata import version
from trading_request.intake import accept_request, ResearchRequest
from trading_supervisor.graph import build_graph
print('Interpreter:', sys.executable)
print('LangGraph:', version('langgraph'))
print('Both local packages imported successfully')
PY
```

Expected interpreter suffix: `supervisor_phase/.venv/bin/python`; expected LangGraph: `1.2.16`. Select this interpreter in VS Code for Phase 2 work. The dependency file pins the versions used in local verification; it is not a hash-locked supply-chain manifest.

## Step 4: Recheck Phase 1

```bash
python -m pytest request_phase/tests -v
```

The previously supplied suite has 40 tests; use the current count if your suite has grown. **Stop if any test fails in the new environment.** Resolve dependency or contract changes before introducing supervisor behavior. Do not weaken existing assertions to make the new phase pass.

## Step 5: Understand the handoff

Pass the **complete intake receipt**, not only `accepted['initial_state']`:

```python
from pathlib import Path
from trading_request.intake import accept_request
from trading_supervisor.contracts import state_from_intake

accepted = accept_request(
    'examples/requests/valid.json',
    root=Path('request_phase'),
    allow_fixtures=True,
)
queued_state = state_from_intake(accepted, allow_fixtures=True)
```

The adapter checks receipt status, versioned request structure, request-hash consistency, and agreement between the request and its proposed initial state. It attaches request/specification/manifest hashes to `lineage` and sets `execution_authorized=False`.

**Why not pass `initial_state` directly?** The Phase 1 initial state does not include its receipt's hashes. The explicit adapter preserves those values rather than losing provenance at the phase boundary.

Fixture opt-in appears at both boundaries intentionally. The supplied examples are metadata-only smoke fixtures, not proof that real bars exist. The CLI calls Phase 1 afresh; accepting a previously saved receipt programmatically does not re-read the referenced files. Hash consistency detects accidental changes, not forged receipts or unauthorized submissions.

Test this boundary:

```bash
python -m pytest supervisor_phase/tests/test_handoff.py -v
```

## Step 6: Inspect the supervisor

Read `supervisor_phase/src/trading_supervisor/supervisor.py`. Its responsibilities are deliberately narrow:

| Check or action | Required behavior |
|---|---|
| Initial status | Require `queued` |
| Iteration | Require integer zero, not Boolean or float |
| Prior execution | Reject an existing plan, prior events, or execution authorization |
| Request contract | Reuse Phase 1's `ResearchRequest` model, not duplicate its rules |
| Integrity | Compare normalized request hash with lineage |
| Budget | Reject a request exceeding the configured policy cap; do not silently clamp |
| Plan | Describe stages, dependencies, and the bounded research loop |
| Result | Return `status='planned'`, a plan hash, and one audit event |
| Side effects | None: no file writes, network calls, model calls, randomness, or input mutation |

The node returns updates; LangGraph merges them into the existing state.[cite:7] Request fields, iteration zero, and lineage therefore survive unchanged. The audit event has a deterministic ID instead of a clock timestamp; the caller or infrastructure can timestamp receipt publication separately.

Run the pure-node tests:

```bash
python -m pytest supervisor_phase/tests/test_supervisor.py -v
```

## Step 7: Understand dependency policy

The safe default is:

```text
data -> regime -> signal -> calibration -> backtest -> diagnostics -> reporting
```

This is **future execution-plan metadata**. The actual Phase 2 graph still contains only the supervisor.

If a regime classifier is verified to consume the raw immutable snapshot independently, set `regime_input='snapshot'`. The plan then records:

```text
data -------+
            +-> signal -> calibration -> backtest -> diagnostics -> reporting
regime -----+
```

Do not enable this mode merely for speed: it is valid only if the classifier does not need data-agent output. One-pass dependencies live in `stages`; the possible diagnostics-to-calibration loop is a separate `iteration_loop` descriptor with the preserved iteration budget. No diagnostics thresholds or statistical acceptance criteria are invented by this minimal planner.

## Step 8: Test the graph

The graph factory is intentionally small:

```python
from langgraph.graph import START, END, StateGraph
from .contracts import SupervisorState
from .supervisor import strategy_supervisor

builder = StateGraph(SupervisorState)
builder.add_node('strategy_supervisor', strategy_supervisor)
builder.add_edge(START, 'strategy_supervisor')
builder.add_edge('strategy_supervisor', END)
graph = builder.compile()
```

The official Graph API documents these entry/exit edges and state-update semantics.[cite:11] `TypedDict` describes state for tools and type checkers; the adapter and reused Pydantic request model perform the actual boundary checks in this implementation.

```bash
python -m pytest supervisor_phase/tests/test_graph.py -v
```

These tests prove that intake output crosses the graph boundary, inputs and lineage survive, only the supervisor executes, the graph finishes at `planned`, checkpoint inspection works, and socket connection attempts are prohibited during a graph run. A fresh graph/checkpointer per test follows LangGraph's testing guidance.[cite:5]

## Step 9: Run end-to-end planning

Use the unchanged Phase 1 valid example:

```bash
python -m trading_supervisor examples/requests/valid.json \
  --root request_phase \
  --allow-fixtures \
  --output runs/supervisor-plan-001.json

echo $?
```

Expected exit code: `0`. Expected output file: `request_phase/runs/supervisor-plan-001.json`. It contains the complete planned state, not just a plan fragment.

Assert the result:

```bash
python - <<'PY'
import json
from pathlib import Path
value = json.loads(Path('request_phase/runs/supervisor-plan-001.json').read_text())
assert value['status'] == 'planned'
assert value['iteration'] == 0
assert value['execution_authorized'] is False
assert value['execution_plan']['mode'] == 'plan_only'
assert len(value['events']) == 1
assert len(value['plan_sha256']) == 64
assert value['lineage']['validation_scope'] == 'metadata_only'
print('PASS: supervisor planned the request without executing workers')
PY
```

The CLI disables automatic LangSmith tracing for this local exercise. No checkpoint database is created by default. The output writer refuses overwrites; rerun without `--output` or choose a new filename.

## Step 10: Prove policy rejection

The example request asks for three iterations. Reject it with a policy cap of two:

```bash
python -m trading_supervisor examples/requests/valid.json \
  --root request_phase \
  --allow-fixtures \
  --iteration-cap 2 \
  --output runs/rejected-supervisor-plan.json

echo $?
test ! -e request_phase/runs/rejected-supervisor-plan.json && echo 'PASS: no plan receipt created'
```

Expected exit code: `2`, stderr status `rejected`, and no new output receipt. This validates a supervisor-specific constraint without changing the already valid Phase 1 request. Use a previously unused output path for this check.

Additional CLI tests cover fixture rejection by default, receipt overwrite protection, output-path confinement, and the explicit independent-snapshot policy:

```bash
python -m pytest supervisor_phase/tests/test_cli.py -v
```

## Step 11: Run all Phase 2 tests

```bash
python -m pytest supervisor_phase/tests -v
python -m compileall -q supervisor_phase/src
python -m pip check
```

**Local verification: 50 Phase 2 tests passed** under Python 3.12.8 and LangGraph 1.2.16. The prior files were unavailable in this session, so intake integration used a temporary reconstruction of the previously supplied Phase 1 implementation. Its real `accept_request()` was called, not a mocked success response. The actual user repository and its Phase 1 suite were not executed here. See `supervisor_phase/verification/TEST-SCOPE.md` for the exact boundary of this evidence.

Run both phases locally as separate commands to keep their results clear:

```bash
python -m pytest request_phase/tests -v
python -m pytest supervisor_phase/tests -v
```

## Step 12: Inspect an optional checkpoint

No checkpointing is needed for the basic smoke test. To learn state inspection without installing a database, run:

```bash
python - <<'PY'
from pathlib import Path
from langgraph.checkpoint.memory import InMemorySaver
from trading_request.intake import accept_request
from trading_supervisor.contracts import state_from_intake
from trading_supervisor.graph import build_graph

accepted = accept_request('examples/requests/valid.json', root=Path('request_phase'), allow_fixtures=True)
state = state_from_intake(accepted, allow_fixtures=True)
graph = build_graph(checkpointer=InMemorySaver())
config = {'configurable': {'thread_id': state['request_id']}}
graph.invoke(state, config=config)
snapshot = graph.get_state(config)
assert snapshot.values['status'] == 'planned'
assert snapshot.next == ()
print('Checkpoint status:', snapshot.values['status'])
print('Pending nodes:', snapshot.next)
PY
```

A checkpointer uses `thread_id` to identify saved graph state.[cite:6] `InMemorySaver` is for tests and local experiments; its state disappears when the process ends, so this is not a crash-recovery demonstration.[cite:10] Do not reuse a completed thread for a different request. Durable persistence and run-id/idempotency design belong to a later milestone.

## Step 13: Commit and check CI

Review the new workflow at `.github/workflows/strategy-supervisor.yml`. It installs both local packages, runs the existing Phase 1 suite, runs the 50 Phase 2 tests, and smoke-tests an actual request-to-plan handoff. GitHub recommends `setup-python` for consistent Python CI and supports running the same pytest commands as locally.[cite:124]

```bash
git status --short
git add supervisor_phase .github/workflows/strategy-supervisor.yml STRATEGY-SUPERVISOR-GUIDE.md
git diff --cached --stat
git diff --cached --name-only
git commit -m 'Add deterministic strategy supervisor with intake handoff and tests'
git push -u origin feat/strategy-supervisor
```

Verify no `.venv/`, secrets, generated receipts, or price files are staged. The supplied `.gitignore` excludes the new environment and common Python build/test artifacts. The plan output sits under Phase 1's already ignored `runs/` directory. GitHub Actions will run after pushing; it has not already been executed on the user's repository. If organization policy requires immutable action SHAs, replace action version tags with approved revisions.

On GitHub, open **Actions -> Strategy supervisor phases 1 and 2**. Both test steps and the smoke test must be green before merging the pull request. Preserve the existing Phase 1 workflow.

## Troubleshooting

| Symptom | Action |
|---|---|
| `No module named trading_request` | Install both editable subprojects in the active Phase 2 environment |
| pip cannot find the request-phase distribution | Install the two local paths together exactly as shown; do not ask PyPI for the private Phase 1 package |
| Receipt or model validation failure | Compare the real Phase 1 acceptance output with `IntakeReceipt`; adapt the explicit handoff if Phase 1 was changed |
| Unexpected keyword or import error | Inspect `accept_request`'s actual signature and package version; the user repository has not been assumed identical |
| `fixture snapshot rejected` | Use `--allow-fixtures` for metadata smoke fixtures only |
| Policy cap rejection | Raise the policy cap intentionally or submit a new lower-budget request; do not silently alter accepted input |
| File already exists | Choose a new plan-receipt filename or omit `--output` |
| Import or test passes locally but fails in CI | Check the installed package paths, committed fixtures, Python version, and actual workflow failure |

## Phase acceptance criteria

- Existing Phase 1 tests remain green in the new environment.
- The full intake receipt is adapted without losing its lineage hashes.
- The supervisor is deterministic and does not mutate input.
- The graph contains only `START -> strategy_supervisor -> END`.
- Accepted requests produce `planned`, never `running` or `completed`.
- Iteration remains zero and execution remains unauthorized.
- Budget violations reject the plan rather than silently changing the request.
- Dependency policy records whether classification needs prepared data.
- All 50 supplied supervisor tests and the smoke test pass locally.
- Both phases and the smoke test pass in the new GitHub workflow.

## Next boundary

After this milestone, implement the Data Agent with its own artifact contract and tests. Do not turn this plan metadata into execution by simply iterating over stage names: later graph edges must implement dependencies, barriers, and the bounded scientific loop explicitly.

This starter is not a production job scheduler, security sandbox, or live-trading approval gate. `execution_authorized=False` is a descriptive safeguard, not an authorization system. Hashes are not digital signatures; underlying bars and file freshness are not verified. File publication is exclusive-create, not a database transaction or crash-safe atomic publication. Events currently have one writer; design a reducer before introducing parallel event writers. Full strategy semantics, statistical acceptance policy, retries for real I/O, resource budgets, and persistent checkpoints are deliberately out of scope.

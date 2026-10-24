**Run this as a small handoff smoke test from your repository root.** It verifies that the validated request becomes a correctly initialized supervisor state—without running the supervisor yet.

Your original snippet has no `print()` statements, so a successful run would otherwise produce no visible output.

## 1. Activate the environment

In your **VS Code WSL/Ubuntu terminal**, run:

```bash
cd ~/code/trading-research
source supervisor_phase/.venv/bin/activate

pwd
python -c "import sys; print(sys.executable)"
```

Confirm:

- Working directory is your repository root.
- Python points to `supervisor_phase/.venv/bin/python`.

If your repository is elsewhere, replace the `cd` path.

## 2. Check the required files

Run:

```bash
ls request_phase/examples/requests/valid.json
ls request_phase/examples/specs/es_meanrev.json
ls request_phase/data/manifests/demo-es-snapshot-v1.json
```

All three paths should exist for the supplied example.

Then verify the imports:

```bash
python -c "
from trading_request.intake import accept_request
from trading_supervisor.contracts import state_from_intake
print('PASS: both imports work')
"
```

If you get `ModuleNotFoundError`, install both packages into the active environment:

```bash
python -m pip install -e './request_phase[dev]' -e './supervisor_phase[dev]'
```

## 3. Run the handoff test

**Copy and paste this entire block into the terminal**, including the opening and closing `PY` lines. Python’s `-` option executes code supplied through standard input, so no separate script file is required. [docs.python](https://docs.python.org/3/using/cmdline.html)

```bash
python - <<'PY'
import json
from copy import deepcopy
from pathlib import Path

from trading_request.intake import accept_request
from trading_supervisor.contracts import state_from_intake

# Phase 1: validate the request.
accepted = accept_request(
    'examples/requests/valid.json',
    root=Path('request_phase'),
    allow_fixtures=True,
)

assert accepted['status'] == 'request_validated'
print('PASS: Research Request accepted')

# Preserve a copy to check that the adapter does not mutate its input.
before = deepcopy(accepted)

# Phase 2 boundary: prepare the supervisor input state.
queued_state = state_from_intake(
    accepted,
    allow_fixtures=True,
)

assert accepted == before
print('PASS: intake receipt was not modified')

# Check the initial execution state.
assert queued_state['status'] == 'queued'
assert queued_state['iteration'] == 0
assert queued_state['events'] == []
assert queued_state['execution_authorized'] is False
print('PASS: supervisor state initialized correctly')

# Check that every normalized request field survives the handoff.
for key, value in accepted['request'].items():
    assert queued_state[key] == value, f'Request field changed: {key}'
print('PASS: request fields preserved')

# Check that validation lineage survives the handoff.
for key in (
    'request_sha256',
    'strategy_spec_sha256',
    'snapshot_manifest_sha256',
):
    assert queued_state['lineage'][key] == accepted[key], (
        f'Lineage mismatch: {key}'
    )
print('PASS: validation hashes preserved')

print('\n--- Supervisor input state ---')
print(json.dumps(queued_state, indent=2))

print('\nSUCCESS: intake-to-supervisor handoff passed')
PY
```

## 4. Confirm the result

With the supplied implementation, the output should include:

```text
PASS: Research Request accepted
PASS: intake receipt was not modified
PASS: supervisor state initialized correctly
PASS: request fields preserved
PASS: validation hashes preserved

--- Supervisor input state ---
...JSON state...

SUCCESS: intake-to-supervisor handoff passed
```

Immediately afterward, check the exit code:

```bash
echo $?
```

Expected:

```text
0
```

**The status should still be `queued`, not `planned`.** This test only prepares the supervisor’s input; executing the supervisor is the next test.

## 5. Run the automated handoff tests

Run the supplied test module:

```bash
python -m pytest supervisor_phase/tests/test_handoff.py -v
```

Pytest supports invoking a specific test file through `python -m pytest`, using the active Python interpreter. [docs.pytest](https://docs.pytest.org/en/stable/how-to/usage.html)

Once both the smoke test and automated handoff tests pass, continue with:

```bash
python -m pytest supervisor_phase/tests/test_supervisor.py -v
```
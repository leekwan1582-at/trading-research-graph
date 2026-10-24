# Test the Research Request Phase

## Goal

Prove this boundary works before introducing agents, APIs, PostgreSQL, market data, or backtests:

```text
Request JSON -> schema validation -> specification/manifest checks
             -> normalized request + initial state + optional receipt
```

This package does not run or submit a research job. `queued` is an initial-state value, not confirmation that a worker or queue has received anything. Successful validation is metadata-only; it does not prove historical bars exist or that a strategy is profitable.

## Scope and assumptions

The repository has not been inspected. These instructions use `~/code/trading-research` as an example; change the path if yours differs. Run commands in the WSL/Ubuntu terminal attached to VS Code. The implementation uses an isolated `request_phase/` subproject to avoid replacing an existing `pyproject.toml`, Python environment, or application package.

The ZIP contains `request_phase/`, `.github/workflows/research-request.yml`, this guide, and local test evidence. Example metadata is explicitly marked `fixture_only: true`; no historical price data or performance results are included. Fixture snapshots are rejected unless `--allow-fixtures` is supplied.

## Step 1: Open your repository

If already cloned:

```bash
cd ~/code/trading-research
pwd
git status --short
git remote -v
```

If not cloned, copy your actual GitHub clone URL and run:

```bash
mkdir -p ~/code
cd ~/code
git clone YOUR_ACTUAL_CLONE_URL trading-research
cd trading-research
```

Commit or stash unrelated work before proceeding. Create a dedicated branch and open VS Code:

```bash
git switch -c test/research-request-phase
code .
```

## Step 2: Add the starter files

Extract the supplied ZIP into the repository root, retaining its directory structure. Alternatively, use the following command after replacing the ZIP path with its real WSL-visible location:

```bash
unzip -n /actual/path/research-request-phase.zip -d .
```

`-n` avoids overwriting existing files. If matching files already exist, compare them before continuing; mixing different versions can invalidate the tests. The final layout is:

```text
repo/
├── .github/workflows/research-request.yml
├── GUIDE.md
└── request_phase/
    ├── pyproject.toml
    ├── requirements-tested.txt
    ├── .gitignore
    ├── examples/requests/valid.json
    ├── examples/specs/es_meanrev.json
    ├── data/manifests/demo-es-snapshot-v1.json
    ├── src/trading_request/__init__.py
    ├── src/trading_request/__main__.py
    ├── src/trading_request/intake.py
    └── tests/test_intake.py
```

## Step 3: Create an isolated environment

Use Python 3.12, or another Python 3.11+ interpreter. Do not replace your existing trading environment.

```bash
python3 --version
python3 -m venv request_phase/.venv
source request_phase/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r request_phase/requirements-tested.txt
python -m pip install -e './request_phase[dev]'
python -c 'import sys; print(sys.executable)'
```

The last command should point inside `request_phase/.venv/`. If your default `python3` is 3.10, use an installed Python 3.12 executable instead. If venv support is missing on Ubuntu, install the matching Python venv package for your interpreter. In VS Code, select this environment via **Python: Select Interpreter** for this exercise, then switch back when returning to your other project work.

## Step 4: Inspect the input

Open `request_phase/examples/requests/valid.json`:

```json
{
  "schema_version": "1",
  "request_id": "demo-es-meanrev-001",
  "strategy_spec_uri": "examples/specs/es_meanrev.json",
  "dataset_snapshot_id": "demo-es-snapshot-v1",
  "universe": ["ES"],
  "start": "2020-01-01",
  "end": "2025-12-31",
  "max_iterations": 3
}
```

Both dates are inclusive in this starter. `start` must be earlier than `end`. Duplicate instruments are rejected. The iteration budget must be an integer between 1 and 20; numeric strings and booleans are rejected. Unknown fields are rejected to catch typos.

For this local-only phase, `strategy_spec_uri` deliberately holds a path relative to `--root`; `file://`, `s3://`, and network URIs are not supported. The field name is retained for compatibility with the earlier design. Add explicit authorized resolvers later rather than making arbitrary URI requests.

The strategy JSON contains only identification, frequency, and the research question. It is not an executable strategy specification. The dataset manifest is a test fixture describing a hypothetical catalog entry, not evidence that ES bars are installed.

Pydantic supports JSON model validation and rejecting unexpected fields through `extra='forbid'`.[cite:103]

## Step 5: Run a successful smoke test

From the repository root:

```bash
python -m trading_request examples/requests/valid.json \
  --root request_phase \
  --allow-fixtures \
  --output runs/demo-es-meanrev-001.json

echo $?
```

Expected exit code: `0`. Expected receipt: `request_phase/runs/demo-es-meanrev-001.json`. The result includes:

```json
{
  "status": "request_validated",
  "validation_scope": "metadata_only",
  "fixture_only": true,
  "initial_state": {
    "status": "queued",
    "iteration": 0,
    "events": []
  }
}
```

This is an excerpt: the actual receipt also contains the normalized request, request hash, strategy-specification hash, manifest hash, and full initial state.

The CLI refuses to overwrite receipts. For repeated smoke tests omit `--output` to print results only, or use a fresh output filename. This is overwrite protection, not a complete run-id/idempotency registry.

Inspect the receipt:

```bash
python -m json.tool request_phase/runs/demo-es-meanrev-001.json
```

## Step 6: Prove invalid requests fail

Create a separate invalid fixture; do not edit the valid example:

```bash
python - <<'PY'
import json
from pathlib import Path
source = Path('request_phase/examples/requests/valid.json')
payload = json.loads(source.read_text())
payload['max_iterations'] = 0
Path('request_phase/examples/requests/invalid.json').write_text(
    json.dumps(payload, indent=2) + '\n'
)
PY

python -m trading_request examples/requests/invalid.json \
  --root request_phase \
  --allow-fixtures \
  --output runs/invalid-should-not-exist.json

echo $?
test ! -e request_phase/runs/invalid-should-not-exist.json && echo 'PASS: no receipt created'
```

Expected exit code: `2`; expected stderr JSON status: `rejected`; expected receipt: absent.

Repeat with distinct invalid copies if desired: missing `request_id`, malformed date, reversed dates, empty or duplicate universe, absent strategy file, unknown snapshot ID, unsupported instrument, or dates beyond manifest coverage. Remove `--allow-fixtures` from a valid fixture command to confirm demo-only snapshots are rejected by default.

## Step 7: Run automated tests

```bash
python -m pytest request_phase/tests -v
```

The supplied suite was executed in an isolated Python 3.12.8 environment: **40 tests passed**. This is local execution evidence for the supplied package, not a claim about your repository or GitHub CI.

The tests cover required fields, defaults, field types, iteration bounds, duplicate symbols, dates, unknown fields, missing references, snapshot mismatches, path traversal, symlink escapes, hash stability, valid/invalid CLI behavior, malformed JSON, output confinement, and receipt overwrite protection.

Pytest parametrization runs multiple input cases through one test function.[cite:101] Its `tmp_path` fixture creates a separate temporary directory for each test, so missing-file and reference checks do not depend on your personal data folders.[cite:102]

Optional syntax check:

```bash
python -m compileall -q request_phase/src
```

## Step 8: Run GitHub CI

Inspect `.github/workflows/research-request.yml`. It checks out the repository, configures Python 3.12, installs the tested dependencies and editable subproject, runs pytest, and performs the fixture smoke test. GitHub documents `setup-python` and pytest as its standard Python CI workflow.[cite:87]

Review and commit only the intended files:

```bash
git status --short
git add request_phase .github/workflows/research-request.yml GUIDE.md
git diff --cached --stat
git diff --cached --name-only
git commit -m 'Add isolated research-request validation phase and tests'
git push -u origin test/research-request-phase
```

Confirm the staged paths contain no secrets, real datasets, `.venv/`, or generated receipts. The subproject `.gitignore` excludes its environment, caches, editable-install metadata, and `runs/`.

Open GitHub **Actions -> Research request phase** and inspect the run. Create a pull request when the tests and smoke test are green. No API secrets or paid services are required for these tests. If the organization requires full-SHA-pinned actions, replace the example version tags with approved immutable action revisions.

## Completion checklist

- Valid input produces a normalized request, hashes, and initial state.
- Invalid input exits with `2` and does not create a success receipt.
- Missing specifications and manifests fail before any worker is invoked.
- Snapshot identifiers, instruments, and date coverage agree.
- Fixture-only snapshots require explicit opt-in.
- Request/specification/output paths stay within the configured root.
- All 40 supplied tests pass locally.
- GitHub Actions passes on the branch or pull request.

## Next boundary

After this phase is green, pass `accepted['initial_state']` to a tiny `START -> supervisor -> END` graph and assert that a supervisor stub receives the expected request. Keep that integration test separate from these pure intake tests. Do not connect live data, calibration, or execution merely to validate the request phase.

Production expansion still needs full strategy semantics, data-file integrity and actual coverage checks, runtime budgets, authenticated submission, an idempotency registry, atomic durable receipt publishing, and authorization. File confinement here is a local trusted-workspace guard, not a hardened multi-tenant sandbox; writable symlinks and filesystem races require stronger isolation. Hashing request/specification/manifest bytes does not verify the underlying price files.

# Test Your Research Request Phase

**Start with a small, isolated intake validator—not the complete agent graph.** The first milestone should prove that a research-request JSON file can be validated, its strategy and dataset references can be checked, and a normalized initial state can be produced without calling any agents, downloading prices, running backtests, or submitting orders.

The accompanying starter package implements this milestone and includes 40 locally executed passing tests, a command-line entry point, clearly labelled metadata fixtures, a complete WSL guide, and a GitHub Actions workflow. The repository itself has not been inspected or modified; the commands below assume a local checkout at `~/code/trading-research`, which should be changed if the actual location differs.

## Define the boundary

```text
Research request JSON
        |
        v
Validate schema and constraints
        |
        v
Resolve local strategy specification and snapshot manifest
        |
        v
Check identifiers, instruments, and date coverage
        |
        v
Normalized request + initial state + optional JSON receipt
```

This is a metadata-only acceptance test. A successful result does not prove that historical bars exist, that the strategy specification is executable, or that any research worker has received the job. The initial-state status `queued` is a proposed state value, not an actual queue submission.

## Open the repository

Run these commands in the WSL/Ubuntu terminal:

```bash
cd ~/code/trading-research
pwd
git status --short
git remote -v
```

Commit or stash unrelated work first, then create a branch:

```bash
git switch -c test/research-request-phase
code .
```

If the repository exists only on GitHub, clone it using its actual clone URL before this step. Do not run `git init` inside an existing checkout.

## Add the starter files

Extract the supplied starter ZIP into the repository root without flattening its directories. It adds an isolated `request_phase/` subproject rather than overwriting an existing root `pyproject.toml`:

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
    ├── src/trading_request/intake.py
    ├── src/trading_request/__main__.py
    └── tests/test_intake.py
```

Review matching paths if the repository already contains any of these files. The package includes example request metadata only; it contains no historical price series or fabricated strategy-performance results.

## Prepare Python

Use Python 3.11 or newer. The supplied package was tested under Python 3.12.8; the CI example uses Python 3.12.

```bash
python3 --version
python3 -m venv request_phase/.venv
source request_phase/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r request_phase/requirements-tested.txt
python -m pip install -e './request_phase[dev]'
python -c 'import sys; print(sys.executable)'
```

The interpreter path should end in `request_phase/.venv/bin/python`. If the default `python3` is 3.10, use an installed Python 3.12 executable instead; leave the existing trading/backtesting environment unchanged.

## Inspect the request

The example request is:

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

The proposed contract requires nonempty identifiers, a nonempty universe without duplicates, ordered inclusive dates, and an integer iteration budget from 1 to 20. It rejects unexpected fields, including misspelled settings such as `max_iteration`; Pydantic provides JSON model validation and `extra='forbid'` for this purpose.[^1]

For this starter only, `strategy_spec_uri` is a path relative to `--root`. The field name is retained from the earlier architecture, but remote URIs and `file://` are intentionally unsupported. The minimal strategy specification is not a complete executable trading strategy.

## Run valid input

From the repository root:

```bash
python -m trading_request examples/requests/valid.json \
  --root request_phase \
  --allow-fixtures \
  --output runs/demo-es-meanrev-001.json

echo $?
```

Expected exit code: `0`. Expected receipt location: `request_phase/runs/demo-es-meanrev-001.json`.

The receipt includes `status: request_validated`, `validation_scope: metadata_only`, `fixture_only: true`, the normalized request, SHA-256 hashes of request/specification/manifest, and an initial state containing iteration zero and an empty event list. The manifest is explicitly marked as a fixture and requires the `--allow-fixtures` flag; it is not a claim that ES market data is present.

Inspect the full receipt:

```bash
python -m json.tool request_phase/runs/demo-es-meanrev-001.json
```

The CLI refuses to overwrite an existing receipt. For repeat runs, omit `--output` or use a fresh filename. This is overwrite protection, not a complete idempotency registry.

## Run invalid input

Create a separate invalid example:

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

Expected exit code: `2`; the CLI writes rejection details to stderr, and no success receipt should exist. Repeat with a missing identifier, reversed dates, an unknown snapshot, or an unsupported instrument if manual inspection of each error is useful.

## Run the automated suite

```bash
python -m pytest request_phase/tests -v
```

The supplied implementation completed **40 passing tests** in the local isolated environment. This is execution evidence for the supplied package only—not a claim that tests have already passed in the user's repository or on GitHub.

| Area | Checks included |
|---|---|
| Input contract | Required fields, defaults, unknown fields, identifier constraints, strict iteration types and bounds |
| Research window | Malformed dates, reversed dates, coverage outside the manifest |
| Universe | Empty list, blank instrument, duplicate instrument, unsupported instrument |
| References | Missing specification, missing manifest, mismatched snapshot ID |
| File boundaries | Absolute paths, parent traversal, symlink escape, output escape |
| Reproducibility | Stable normalized request hash and changes when meaningful input changes |
| CLI behavior | Valid receipt, invalid input without receipt, malformed JSON, overwrite rejection |

The suite uses parametrization to exercise multiple input cases and `tmp_path` to isolate filesystem fixtures between tests. An additional syntax check can be run with:[^2][^3]

```bash
python -m compileall -q request_phase/src
```

## Enable GitHub testing

The supplied workflow runs on pushes and pull requests. It checks out the repository, configures Python 3.12, installs the tested dependencies, runs pytest, and runs a valid fixture smoke test; GitHub documents this `setup-python` plus pytest pattern for Python CI.[^4]

Review staged changes before committing:

```bash
git status --short
git add request_phase .github/workflows/research-request.yml GUIDE.md
git diff --cached --stat
git diff --cached --name-only
git commit -m 'Add isolated research-request validation phase and tests'
git push -u origin test/research-request-phase
```

Check that no secrets, live datasets, virtual environments, or generated receipts are staged. Open **GitHub → Actions → Research request phase**, inspect the job, and create a pull request after the tests and smoke test pass. The exercise requires no API keys or paid services.

## Troubleshooting

| Symptom | Action |
|---|---|
| `No module named trading_request` | Activate the new environment and rerun `python -m pip install -e './request_phase[dev]'` |
| Python requirement failure | Use Python 3.11+; do not force installation into the existing 3.10 environment |
| Specification or manifest not found | Run from the repository root and keep `--root request_phase` |
| Fixture rejected | Use `--allow-fixtures` only for the included smoke tests |
| Receipt already exists | Use a new output filename or omit `--output` |
| Local pass, CI failure | Compare checked-in fixture paths, case sensitivity, Python version, dependencies, and the failing job log |

## Phase acceptance

The phase is complete when valid input produces the normalized initial state, invalid input creates no success receipt, all supplied tests pass locally, and the GitHub workflow passes. Stop there before adding the other agents.

The next integration milestone is a separate `START -> supervisor -> END` graph that receives the accepted initial state. Later production work must add full strategy semantics, actual price-file integrity and coverage checks, authenticated submission, durable atomic receipts, and an idempotency registry. Local path confinement in this starter is not a hardened multi-tenant filesystem sandbox, and metadata hashing does not verify the underlying market-data files.

---

## References

1. [pydantic/docs/concepts/models.md at main - GitHub](https://github.com/pydantic/pydantic/blob/main/docs/concepts/models.md) - - `'forbid'`: Providing extra data is not permitted.
...
that will override the `extra` configuratio...

2. [How to parametrize fixtures and test functions](https://docs.pytest.org/en/stable/how-to/parametrize.html) - mark.parametrize allows one to define multiple sets of arguments and fixtures at the test function o...

3. [How to use temporary directories and files in tests](https://docs.pytest.org/en/stable/how-to/tmp_path.html) - The tmp_path_factory is a session-scoped fixture which can be used to create arbitrary temporary dir...

4. [Building and testing Python](https://docs.github.com/en/actions/tutorials/build-and-test-code/python) - To use a pre-installed version of Python or PyPy on a GitHub-hosted runner, use the `setup-python` a...


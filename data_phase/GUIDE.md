# Phase 3 — Data Agent Build and Test Guide

## Objective

Add a deterministic, research-only Data Agent after the passing Strategy Supervisor:

```text
validated request -> strategy_supervisor -> data_agent -> END
                         queued -> planned -> data_ready
```

The milestone reads an already approved local Parquet snapshot, verifies cross-phase lineage, validates OHLCV, writes immutable prepared artifacts, and returns references through LangGraph state. It does not call an LLM, broker, exchange API, or trading engine.

## Important integration boundary

This extension targets the Phase 1 and Phase 2 interfaces used in the preceding guides:

- `trading_request.intake.accept_request`
- `trading_supervisor.contracts.state_from_intake`
- `trading_supervisor.supervisor.strategy_supervisor`
- Supervisor output status `planned`
- Replacement semantics for the `events` state field

Do not overwrite your passing packages. Install this extension beside them and run the compatibility preflight. If the preflight reports a reducer or schema mismatch, stop and adapt the small boundary before running Phase 3.

## What is included

- `src/trading_data/contracts.py`: accepted-request, catalog, access, and graph-state contracts
- `src/trading_data/validation.py`: deterministic OHLCV checks
- `src/trading_data/storage.py`: project-root confinement and immutable publication
- `src/trading_data/agent.py`: planned-state gate, lineage checks, validation, and artifact receipt
- `src/trading_data/reader.py`: downstream hash-verifying reader
- `src/trading_data/graph.py`: supervisor-to-data LangGraph
- `src/trading_data/seed_demo.py`: explicit offline test-workspace seeder
- `src/trading_data/preflight.py`: installed Phase 1/2 compatibility test
- `tests/`: positive, negative, corruption, idempotency, no-network, graph, and CLI tests
- `tests/fixtures/`: two days of real BTCUSDT 1-minute observations, plus provenance
- `verification/`: captured local verification evidence
- `.github/workflows/data-agent.yml`: CI example, placed at repository root by the ZIP

The fixture is a small transformation of Binance's January 2024 BTCUSDT spot kline archive. The upstream SHA-256 checksum was verified before transformation. It is not synthetic, but it remains test-only and is not evidence of strategy performance.

## Step 1 — Create a branch

From your repository root:

```bash
cd ~/code/trading-research
git status --short
git switch -c feat/data-agent
```

Keep a clean working tree or record existing changes before extraction.

## Step 2 — Extract the extension

Extract `data-agent-phase3.zip` into the repository root. It should produce:

```text
data_phase/
.github/workflows/data-agent.yml
```

Then inspect before installing:

```bash
find data_phase -maxdepth 3 -type f | sort
git status --short
git diff -- .github/workflows/data-agent.yml data_phase/pyproject.toml
```

Do not replace `request_phase/` or `supervisor_phase/`.

## Step 3 — Create an isolated environment

```bash
python3 -m venv data_phase/.venv
source data_phase/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r data_phase/requirements-tested.txt
python -m pip install -e './request_phase[dev]' \
                      -e './supervisor_phase[dev]' \
                      -e './data_phase[dev]'
python -m pip check
```

Expected final line:

```text
No broken requirements found.
```

The lock snapshot records the versions used for supplied verification. If your existing packages intentionally require different compatible versions, resolve the environment and rerun every phase rather than forcing the snapshot.

## Step 4 — Run upstream tests

Do not continue if either earlier phase regresses:

```bash
python -m pytest request_phase/tests -v
python -m pytest supervisor_phase/tests -v
```

## Step 5 — Run compatibility preflight

```bash
export LANGSMITH_TRACING=false
export LANGCHAIN_TRACING_V2=false
python -m trading_data.preflight
```

Expected first line:

```text
PASS: installed Phase 1 and Phase 2 contracts match this Phase 3 adapter
```

The command also prints the actual files providing `accept_request`, `state_from_intake`, and `strategy_supervisor`. Confirm they point into your repository—not an unrelated globally installed package.

### If preflight stops

- Missing state field: update `DataState` and the adapter to your actual supervisor contract.
- `events uses a reducer`: change `data_agent()` to return only its new event; do not return the complete event list.
- Hash or plan mismatch: compare the Phase 2 canonicalization and execution-plan structure with `agent.py`.
- Different status name: establish an explicit mapping; do not weaken the planned-state gate.

## Step 6 — Run Phase 3 tests

```bash
python -m pytest data_phase/tests -v
```

The reference build result included in the bundle is:

```text
76 passed
```

The exact duration can differ. The tests use `tmp_path`, so successful runs do not modify your real research datasets.

### What the tests prove

- Correct two-day selection from real observations
- Strict UTC timestamp type and one-minute alignment
- Exact schema and numeric typing
- No null, NaN, infinity, duplicate, unsorted, missing, or malformed OHLCV rows
- Policy-specific positive-price and 24x7 completeness behavior
- Request, plan, manifest, strategy-specification, catalog, and source hashes remain consistent
- No network access occurs during the Data Agent run
- Input state and raw table are not mutated
- Re-execution reuses identical artifacts
- Existing conflicting or corrupted artifacts are rejected, not overwritten
- A success receipt is not published for invalid data
- `START -> strategy_supervisor -> data_agent -> END` reaches `data_ready`
- `execution_authorized` remains `False` and iteration remains zero

Corruption cases deliberately mutate copies of real observations. Those altered values are negative-test inputs, not market data.

## Step 7 — Seed the offline demo

The seeder copies the bundled real-data regression fixture into a new isolated workspace and creates intake-compatible request, specification, manifest, and data-catalog files.

```bash
rm -rf data_phase/runs/manual-demo
python -m trading_data.seed_demo \
  --root data_phase/runs/manual-demo

find data_phase/runs/manual-demo -maxdepth 4 -type f | sort
```

Before execution, the workspace contains only inputs; no `runs/data/.../receipt.json` exists.

## Step 8 — Execute the full graph

```bash
python -m trading_data \
  requests/valid.json \
  --root data_phase/runs/manual-demo \
  --allow-fixtures \
  --allow-local-data \
  | tee data_phase/runs/manual-demo/final-state.json
```

Expected state properties:

```text
status                 data_ready
iteration              0
execution_authorized   false
events                  strategy_supervisor, data_agent
data_quality.rows       2880
data_quality.status     passed
```

Both permissions are explicit:

- `--allow-fixtures` admits data labelled test-only.
- `--allow-local-data` permits reading and publishing under the supplied project root.

Omit either flag and the run should fail closed with exit code `2`.

## Step 9 — Inspect and verify artifacts

Do not discover datasets by globbing partially written directories. Resolve the commit receipt returned in `data_artifact` and use the verified reader:

```bash
python - <<'PY'
import json
from pathlib import Path
from trading_data.reader import load_prepared

root = Path('data_phase/runs/manual-demo')
state = json.loads((root / 'final-state.json').read_text())
bars, quality, receipt = load_prepared(root, state['data_artifact'])

assert state['status'] == 'data_ready'
assert state['iteration'] == 0
assert state['execution_authorized'] is False
assert bars.num_rows == quality['selected_rows'] == receipt['rows'] == 2880
assert receipt['trading_authorized'] is False

print(bars.schema)
print(json.dumps(quality, indent=2))
print(json.dumps(receipt, indent=2))
print('PASS: committed Data Agent artifacts verified')
PY
```

The prepared table adds `bar_end_utc`. This is the right boundary for a completed bar, but it is not proof of vendor delivery time or point-in-time availability.

## Step 10 — Test fail-closed behavior

### Permission gate

```bash
rm -rf data_phase/runs/rejected-demo
python -m trading_data.seed_demo --root data_phase/runs/rejected-demo
python -m trading_data \
  requests/valid.json \
  --root data_phase/runs/rejected-demo \
  --allow-fixtures
echo "exit=$?"
```

Expected: `data_rejected`, exit code `2`, and no success receipt.

### Resource cap

```bash
python -m trading_data \
  requests/valid.json \
  --root data_phase/runs/rejected-demo \
  --allow-fixtures \
  --allow-local-data \
  --max-input-rows 100
echo "exit=$?"
```

Expected: rejection because the input contains more than 100 rows.

### Tamper test

Use a fresh workspace, alter the source after intake metadata is created, and run:

```bash
rm -rf data_phase/runs/tamper-demo
python -m trading_data.seed_demo --root data_phase/runs/tamper-demo
printf 'tamper' >> data_phase/runs/tamper-demo/data/raw/btc-test.parquet
python -m trading_data \
  requests/valid.json \
  --root data_phase/runs/tamper-demo \
  --allow-fixtures \
  --allow-local-data
echo "exit=$?"
```

Expected: source Parquet hash mismatch and exit code `2`.

## Step 11 — Understand the artifact contract

A successful run publishes three files under a content-derived directory:

```text
runs/data/<artifact_id>/bars.parquet
runs/data/<artifact_id>/quality.json
runs/data/<artifact_id>/receipt.json
```

`receipt.json` is published last and acts as the commit marker. It binds:

- Request and supervisor lineage
- Execution-plan hash
- Catalog and source hashes
- Software versions
- Prepared-bars hash and byte count
- Quality-report hash and byte count
- Timestamp convention and availability warning

Identical retries reuse existing files. Different bytes at the same content-derived destination are treated as corruption or conflict; the code never overwrites them.

## Step 12 — Connect your real snapshot

Do not relabel the bundled BTC fixture as ES or as another asset. For your data:

1. Export a frozen Parquet snapshot with exactly these columns: `timestamp`, `symbol`, `open`, `high`, `low`, `close`, `volume`.
2. Use Arrow `timestamp[..., tz=UTC]` for `timestamp`; naive or non-UTC timestamp metadata is rejected.
3. Keep rows sorted by `symbol`, then `timestamp`, with unique `(symbol, timestamp)` keys.
4. Add a Phase 1 manifest under `data/manifests/<snapshot_id>.json`.
5. Add a separate Phase 3 catalog under `data/catalog/<snapshot_id>.json`.
6. Put the exact source Parquet SHA-256 and intake-manifest SHA-256 in the catalog.
7. Set `fixture_only: false` for an approved research snapshot.
8. Point the accepted request to the snapshot ID and matching strategy specification.
9. Run without `--allow-fixtures`, but keep `--allow-local-data`.

### Calendar policy

Use `continuous_24x7` only when every bar is expected continuously across the entire UTC request range, as in the crypto demo. For ES, equities, holidays, maintenance windows, or exchange sessions, start with `unchecked`; it will validate ordering, duplicates, grid alignment, values, and requested rows but will clearly report that session completeness was not checked. Implement an exchange-calendar adapter before claiming complete coverage.

### Price policy

`positive` is appropriate for this BTC fixture but is not a universal market-data truth. Use `allow_nonpositive` for datasets where valid observations can be zero or negative; OHLC consistency and finiteness still apply.

## Step 13 — Add provider adapters later

Keep downloads outside this milestone. A production provider adapter should create and seal the source snapshot before the request reaches the graph. It should handle:

- Authentication and rate limiting
- Raw-response retention
- Vendor checksum or signed-object verification
- Timestamp unit normalization
- Pagination and retry idempotency
- Symbol mapping and contract metadata
- Corporate actions, continuous-futures construction, and session calendars where applicable
- Point-in-time and survivorship controls

The Data Agent should continue consuming an immutable snapshot rather than downloading data during graph execution.

## Step 14 — Run CI locally

Run the same sequence as the included workflow:

```bash
python -m pip check
python -m pytest request_phase/tests -v
python -m pytest supervisor_phase/tests -v
python -m pytest data_phase/tests -v
```

Review `.github/workflows/data-agent.yml` before committing, especially if your package names, Python version, or workflow conventions differ.

## Step 15 — Review and commit

```bash
git status --short
git diff --check
git diff --stat
```

Do not commit:

- `data_phase/.venv/`
- `data_phase/runs/`
- credentials, API keys, or unrestricted vendor datasets

Then:

```bash
git add data_phase .github/workflows/data-agent.yml
git commit -m "feat: add deterministic data agent"
git push -u origin feat/data-agent
```

## Acceptance criteria

Phase 3 is complete only when:

- Phase 1, Phase 2, and Phase 3 tests all pass.
- Compatibility preflight points at your repository packages.
- Valid planned state produces `data_ready`.
- Raw source, manifest, specification, request, and plan lineage are verified.
- Invalid, changed, oversized, incomplete, or unauthorised inputs fail before success receipt publication.
- Artifact reads verify hashes through the commit receipt.
- Retry produces the same artifact references without overwriting files.
- Iteration remains zero and trading authorization remains false.
- No Regime, Signal, Calibration, Backtest, Diagnostics, or Reporting node executes.

The next milestone can add the Regime Agent after it consumes only the verified Data Agent receipt. Do not pass an unverified filesystem path directly to it.

**The Backtest Agent is the frozen-execution evaluator: it takes verified data, fixed signal artifacts, and approved calibration parameters, then simulates trades under a declared execution model to produce immutable performance artifacts for diagnostics.**

This specification is **proposed only**. It is not yet implemented, repository-integrated, or packaged for download.

## 1. Purpose

The Backtest Agent answers:

> “Given this exact strategy configuration, signal stream, and calibrated parameters, what would the simulated trading results have been under the declared execution and cost model?”

It is the **first place** in the pipeline where full strategy P&L, trade paths, equity curves, and drawdowns are computed as primary outputs.

### Included

- Verified input loading
- Frozen-parameter execution
- Trade simulation
- Cost and slippage application
- Equity and drawdown accounting
- Artifact publication
- Deterministic reproducibility

### Excluded

- Parameter search
- Regime fitting
- Signal generation
- Strategy approval
- Walk-forward design selection
- Diagnostic interpretation
- Live trading or broker routing

**A successful backtest run means the simulation completed correctly—not that the strategy is good.**

## 2. Pipeline placement

```text
Approved Data Bundle
        │
        ▼
   Regime Agent
        │
        ▼
   Signal Agent
        │
        ▼
Calibration Agent
        │
        ▼
    Backtest Agent
┌───────────────────────────────┐
│ Verify all frozen inputs      │
│ Load execution model          │
│ Replay signal → order logic   │
│ Simulate fills and costs      │
│ Mark positions to market      │
│ Publish performance artifacts │
└──────────────┬────────────────┘
               │
        backtest_ready
               │
               ▼
        Diagnostics Agent
```

The Backtest Agent must consume the **selected parameter bundle** from calibration and must not rerun threshold search.

## 3. Inputs

The agent requires verified artifacts with matching lineage.

| Input | Requirement |
|---|---|
| Approved data bundle | Quality accepted, integrity verified |
| Regime bundle, if used | Integrity verified, compatible with data |
| Signal bundle | Integrity verified, matching generation/fold |
| Calibration bundle | `calibration_ready`, selected parameters present |
| Execution configuration | Supported schema, content hash frozen |
| Strategy execution rules | Entry, exit, sizing, holding, and reversal rules frozen |
| Research context | Matching run, generation, request, plan, fold, and instrument scope |

### Identity invariants

At minimum, these identities must match or reference each other consistently:

- `request_sha256`
- `execution_plan_sha256`
- `run_id`
- `generation_id`
- `fold_id`
- `instrument scope`
- `signal_variant_id`
- `calibration_bundle_ref`
- `evaluation_engine_version`

A backtest must block if calibration parameters were selected for a different signal variant, fold, or execution model.

## 4. Core responsibility

The Backtest Agent performs a **frozen replay**.

That means:

1. It does **not** alter parameters.
2. It does **not** inspect held-out results and revise anything.
3. It uses the same declared execution semantics as calibration.
4. It evaluates the intended partition, usually held-out or designated report scope.
5. It publishes complete evidence for diagnostics.

If calibration used a shared evaluation engine, backtest must use the **same engine contract**, not a second loosely equivalent simulator.

## 5. Execution model contract

The execution model must be explicit and versioned.

| Area | Must be fixed |
|---|---|
| Decision timestamp | When a signal becomes actionable |
| Entry event | Next bar open, close, midpoint, etc. |
| Exit event | Fixed according to strategy rules |
| Costs | Commission, fees, spread, slippage |
| Sizing | Fixed units, fixed notional, volatility target, etc. |
| Capital base | Initial equity and currency |
| Mark-to-market | Frequency and price field |
| Position constraints | Max concurrent positions, pyramiding, reversal |
| Failure handling | Missing bar, invalid price, partial fill policy |

### MVP recommendation

For the first version, keep the model simple:

- Single instrument per job
- Full fills only
- No partial fills
- No market impact model
- One position at a time
- No pyramiding
- No direct reversal in the same event
- Deterministic next-event execution
- Flat at partition boundaries unless explicitly configured otherwise

These are engineering constraints, not statements about realistic live execution quality.

## 6. Signal interpretation

The Backtest Agent does not create scores; it interprets already-produced signal artifacts under frozen parameters.

Illustrative logic for a symmetric threshold strategy:

```text
eligible and raw_score >= theta   → long entry intent
eligible and raw_score <= -theta  → short entry intent
otherwise                         → no new entry intent
```

The execution rules then determine:

- whether an entry is allowed,
- whether an existing position blocks a new one,
- whether exits occur first,
- whether re-entry is allowed on the same event,
- whether a signal on an ineligible row is ignored.

### Important separation

| Item | Owned by |
|---|---|
| Raw score | Signal Agent |
| Threshold `theta` | Calibration Agent |
| Fill timing | Backtest execution model |
| P&L | Backtest Agent |

## 7. Partition rules

Use explicit half-open intervals:

```text
backtest_start <= t < backtest_end
```

The Backtest Agent must never use this partition to recalibrate or reselect parameters.

### Boundary rules

The specification must define:

- whether positions may be opened near the end of the partition,
- whether open positions are liquidated at boundary,
- how liquidation price is chosen,
- whether liquidation incurs normal costs,
- whether missing terminal prices block the run.

For MVP, recommended boundary behavior:

- No new entry if the maximum holding horizon cannot complete inside the backtest partition under the declared execution model.
- Force liquidation at the final allowed execution event.
- Apply normal transaction costs.
- Block if required liquidation data is unavailable.

Do not silently drop unfinished trades.

## 8. Position state machine

The agent should use an explicit deterministic state machine.

### Suggested states

```text
flat
long_open
short_open
pending_long_entry
pending_short_entry
pending_exit
```

### Suggested transitions

| Current state | Event | Next state |
|---|---|---|
| `flat` | Long entry accepted | `pending_long_entry` |
| `flat` | Short entry accepted | `pending_short_entry` |
| `pending_long_entry` | Fill confirmed | `long_open` |
| `pending_short_entry` | Fill confirmed | `short_open` |
| `long_open` | Exit triggered | `pending_exit` |
| `short_open` | Exit triggered | `pending_exit` |
| `pending_exit` | Exit filled | `flat` |

The exact event ordering must be versioned and identical between calibration and backtest.

A successful backtest must never rely on ambiguous same-timestamp ordering.

## 9. Trade and equity accounting

The Backtest Agent must publish at least:

- trade ledger,
- per-bar equity curve,
- realized and unrealized P&L,
- drawdown series,
- summary statistics.

### Required accounting definitions

| Metric | Definition source |
|---|---|
| Gross P&L | Price movement before costs |
| Net P&L | Gross P&L after all declared costs |
| Equity | Initial capital + realized + unrealized P&L |
| Drawdown | Equity relative to running peak |
| Exposure | Fraction of time or bars with open position |
| Turnover | Number of entries/exits or notional turnover |

Do not mix gross and net metrics without explicit labeling.

### Futures-specific note

For futures, P&L must use the declared tick size and contract multiplier. A generic percentage return on price is not sufficient unless the contract explicitly defines that model.

## 10. Output artifacts

### Required bundle

```text
backtest-bundles/<bundle_id>/
├── trades.parquet
├── equity.parquet
├── summary.json
├── backtest-report.json
├── execution-config.json
└── manifest.json
```

### `trades.parquet`

Minimum suggested fields:

| Column | Meaning |
|---|---|
| `trade_id` | Stable unique identifier |
| `instrument` | Instrument |
| `direction` | Long or short |
| `entry_signal_time` | When the entry became actionable |
| `entry_fill_time` | Actual simulated fill time |
| `entry_price` | Fill price |
| `exit_signal_time` | Exit trigger time |
| `exit_fill_time` | Simulated exit time |
| `exit_price` | Fill price |
| `quantity` | Position size |
| `gross_pnl` | Before costs |
| `total_cost` | Total transaction costs |
| `net_pnl` | After costs |
| `holding_bars` or `holding_time` | Duration |
| `exit_reason` | Why the trade closed |

### `equity.parquet`

Suggested fields:

| Column | Meaning |
|---|---|
| `timestamp` | Mark-to-market timestamp |
| `instrument` or portfolio key | Scope |
| `position_state` | Flat/long/short |
| `position_qty` | Current size |
| `mark_price` | Marking price |
| `realized_pnl` | Cumulative realized P&L |
| `unrealized_pnl` | Current unrealized P&L |
| `equity` | Total equity |
| `drawdown` | Drawdown from running peak |

### `summary.json`

Minimum summary statistics:

- total trades
- win rate
- gross profit
- gross loss
- net profit
- average trade
- median trade
- maximum drawdown
- longest drawdown duration
- exposure
- turnover
- ending equity
- return on initial capital

The Backtest Agent may compute these, but interpretation belongs to diagnostics.

## 11. State and statuses

Suggested statuses:

| Status | Meaning |
|---|---|
| `backtest_running` | Execution has started |
| `backtest_ready` | Valid bundle published |
| `backtest_blocked` | Missing or incompatible prerequisites |
| `backtest_failed` | Simulation or publication failed |

Conceptual success update:

```python
{
    "status": "backtest_ready",
    "backtest_bundle_ref": "...",
    "backtest_manifest_sha256": "...",
    "backtest_report_ref": "...",
}
```

These field names are proposed, not verified against your repository.

### Routing invariant

```text
Diagnostics Agent may execute only if:
    backtest_ready
    AND bundle integrity verifies
    AND generation/fold identities match
```

Blocked or failed outcomes must not leave stale successful references in shared state.

## 12. Failure and blocking conditions

The agent must block or fail on any of the following:

- missing calibration bundle
- wrong fold or signal variant
- mismatched execution engine version
- modified or unverifiable upstream artifact
- unsupported price representation
- missing required fill price
- missing required liquidation event
- non-finite trade or equity values
- ambiguous timestamp ordering under current rules
- incomplete publication of required output files

### Block vs fail

| Outcome | Meaning |
|---|---|
| `blocked` | Preconditions or compatibility rules were not satisfied |
| `failed` | Execution started but could not complete reliably |

Example:

- Wrong signal variant → `blocked`
- Disk write interruption during artifact publication → `failed`

## 13. Determinism and reproducibility

The Backtest Agent must be reproducible.

### Required rules

- Same verified inputs + same configuration + same engine version = same outputs
- Output row ordering must be deterministic
- No nondeterministic tie handling
- No random slippage unless a seeded stochastic model is explicitly versioned
- Retry of the same logical run must not create conflicting accepted bundles

### Replay identity

Logical backtest identity should include:

- approved data manifest hash
- regime manifest hash, if applicable
- signal manifest hash
- calibration manifest hash
- execution configuration hash
- engine version
- fold and partition identity

Caching is allowed only after integrity verification.

## 14. Shared-engine consistency

Calibration and backtest must not diverge in execution semantics.

The specification requires a **shared evaluation engine** or a provably identical adapter layer.

### Consistency tests

- same signal + same threshold + same execution config + same partition
- calibration replay of selected candidate
- backtest replay of same candidate
- identical trade ledger and equity outputs, modulo explicitly declared artifact-format differences

If these differ, the calibration result is not trustworthy.

## 15. Acceptance tests

Minimum required tests:

| Test | Expected outcome |
|---|---|
| Verified reference inputs | Valid backtest bundle |
| Wrong fold or generation | Block |
| Wrong calibration bundle | Block |
| Modified signal artifact | Integrity failure |
| Modified execution config | Identity/integrity failure |
| Threshold replay from calibration | Same trades and equity |
| No eligible entries | Valid zero-trade backtest if policy allows |
| Boundary liquidation required | Trade closes correctly or run blocks |
| Missing terminal liquidation price | Block/fail according to contract |
| Long and short symmetry case | Expected trade directions |
| Cost application | Net P&L reflects declared costs |
| Zero/negative or invalid mark price under unsupported model | Fail fast |
| Same-timestamp edge case | Deterministic event ordering |
| Interrupted publication | No consumable partial bundle |
| Retry/resume | No conflicting accepted bundle |
| Any blocked/failed path | Diagnostics spy never invoked |

For multi-instrument support later, add portfolio aggregation tests separately rather than stretching the MVP specification.

## 16. Proposed package structure

```text
backtest_phase/
├── pyproject.toml
├── configs/
│   ├── execution-v1.json
│   └── accounting-v1.json
├── src/trading_backtest/
│   ├── contracts.py
│   ├── inputs.py
│   ├── engine.py
│   ├── state_machine.py
│   ├── accounting.py
│   ├── validation.py
│   ├── artifacts.py
│   ├── node.py
│   └── __main__.py
└── tests/
```

Suggested interfaces:

```python
load_verified_backtest_inputs(...)
validate_execution_config(...)
run_backtest_simulation(...)
validate_backtest_outputs(...)
publish_backtest_bundle(...)
load_verified_backtest_bundle(...)
backtest_agent(state, ...)
```

If you already have a shared engine package, `engine.py` should be a thin adapter rather than a duplicate simulator.

## 17. UI and documentation updates

### Research Control Center

Add a **Run backtest** operation showing:

- selected calibration bundle
- signal variant
- execution configuration
- partition scope
- artifact lineage
- simulation status
- downloadable trades/equity/summary artifacts

Display these independently:

```text
Input integrity
Parameter integrity
Execution-model integrity
Backtest readiness
Diagnostics authority
Research acceptance: Not evaluated
```

### Documentation that must be updated

| Artifact | Required change |
|---|---|
| Architecture | Add frozen replay role of Backtest Agent |
| Calibration spec | Reference shared-engine replay requirement |
| Signal spec | Clarify that no execution semantics are embedded there |
| Diagnostics spec | Consume backtest artifacts rather than rerunning simulation |
| Artifact contracts | Define trade/equity/summary schemas |
| CI workflow | Add shared-engine consistency and bundle validation tests |
| UI spec | Add backtest execution and artifact browsing |

## 18. Implementation milestones

1. Finalize shared execution-engine contract.
2. Implement deterministic state machine.
3. Implement fill and cost logic.
4. Implement equity and drawdown accounting.
5. Add bundle publication and verified loading.
6. Add calibration–backtest replay consistency tests.
7. Integrate graph routing and UI.

**Definition of done:** the Backtest Agent consumes only frozen, verified upstream artifacts; simulates trades under a versioned execution model; publishes reproducible trade and equity evidence; and routes only successful, integrity-verified outputs to diagnostics—without changing parameters or learning from held-out results.
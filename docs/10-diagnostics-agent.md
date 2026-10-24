# Diagnostics Agent Specification

**The Diagnostics Agent is the evidence-and-interpretation stage after backtesting: it verifies the published backtest bundle, computes standardized research diagnostics, evaluates predeclared acceptance rules, and emits the decision-ready artifacts for reporting.**

**Specification:** `diagnostics-agent-v0.1.0`  
**Status:** Proposed contract only. It is not yet implemented, integrated, or packaged for download.

## 1. Purpose

The Diagnostics Agent answers:

> “What do the completed backtest results actually imply about quality, risk, stability, and acceptance under the declared research policy?”

It is the first component allowed to make a structured research judgment such as:

- acceptable for promotion to a broader validation stage,
- rejected,
- inconclusive,
- requires review.

### Included

- Verified loading of backtest artifacts
- Diagnostic metric calculation
- Segmented and conditional performance analysis
- Acceptance-rule evaluation
- Evidence publication
- Final research status for this run stage

### Excluded

- Re-running calibration
- Regenerating signals
- Editing trades
- Backtest repair
- Live trading decisions
- Portfolio optimization
- Strategy redesign

**The Diagnostics Agent can reject a strategy, but it must never silently “improve” one.**

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
        │
        ▼
 Diagnostics Agent
┌────────────────────────────────────┐
│ Verify frozen backtest inputs      │
│ Compute core metrics               │
│ Segment trades and equity paths    │
│ Evaluate acceptance policy         │
│ Publish evidence and decision      │
└──────────────────┬─────────────────┘
                   │
           diagnostics_ready
                   │
                   ▼
          Reporting / dashboard layer
```

The Diagnostics Agent must consume the **published** backtest artifacts, not an in-memory approximation or a separate recomputation.

## 3. Core responsibility

The agent performs **post-simulation analysis without altering the simulated history**.

It must:

1. verify artifact integrity and lineage,
2. compute deterministic diagnostic metrics,
3. compare those diagnostics with a frozen acceptance policy,
4. publish human-readable and machine-readable evidence.

It must not:

- modify trade ordering,
- drop losing trades,
- recompute fills with a new model,
- change initial capital,
- reinterpret costs after the fact,
- use diagnostics to refit parameters in the same evaluation stage.

## 4. Inputs

Required verified inputs:

| Input | Requirement |
|---|---|
| Backtest bundle | `backtest_ready`, manifest verified |
| Trade ledger | Integrity verified |
| Equity curve | Integrity verified |
| Summary statistics | Integrity verified, but not blindly trusted |
| Acceptance policy | Versioned, content-hashed, frozen |
| Research context | Matching request, run, generation, fold, and strategy identities |
| Optional upstream context | Regime labels, signal metadata, calibration outcome, if declared for analysis only |

### Identity invariants

At minimum, the Diagnostics Agent must verify consistency of:

- `request_sha256`
- `execution_plan_sha256`
- `run_id`
- `generation_id`
- `fold_id`
- `signal_variant_id`
- `calibration_manifest_sha256`
- `backtest_manifest_sha256`
- `diagnostics_policy_sha256`

If any of these are incompatible, the run must block.

## 5. Output philosophy

Diagnostics must distinguish four categories:

| Category | Meaning |
|---|---|
| **Measurement** | What happened in the backtest |
| **Assessment** | Whether it meets declared standards |
| **Uncertainty** | How fragile or limited the evidence is |
| **Decision** | Accept / reject / review / inconclusive |

This separation prevents “nice metrics” from being mistaken for approval.

## 6. Diagnostic scope

The MVP should cover five diagnostic domains.

### 6.1 Return quality

- gross and net return
- return on initial capital
- expectancy per trade
- median trade
- profit factor
- payoff ratio
- win rate

### 6.2 Risk and pain

- maximum drawdown
- drawdown duration
- ulcer-style pain metrics, if included
- volatility of equity changes
- worst trade
- worst run of consecutive losses

### 6.3 Sample adequacy

- number of trades
- long/short trade counts
- exposure
- turnover
- average holding duration
- fraction of periods with no trading activity

### 6.4 Stability and concentration

- contribution concentration by trade
- top-N trade contribution share
- month-by-month or segment-by-segment consistency
- regime-conditioned performance, if regime context is declared for analysis
- early-vs-late partition comparison

### 6.5 Execution realism checks

- cost burden as fraction of gross edge
- slippage sensitivity hooks, if configured
- boundary-liquidation dependence
- dependence on a small number of outsized trades

These diagnostics are analytical summaries. They must not mutate the backtest ledger.

## 7. Acceptance policy

Diagnostics must evaluate against a frozen, versioned policy.

Illustrative example:

```yaml
schema_version: "1.0"
policy_id: "single-instrument-mvp-acceptance-v1"

minimums:
  closed_trades: 50
  net_return_on_initial_capital: 0.05
  profit_factor: 1.20
  expectancy_per_trade: 0.0

maximums:
  max_drawdown: 0.15
  top_5_trade_pnl_share: 0.50

required_checks:
  - no_integrity_failures
  - no_missing_trade_ids
  - no_negative_equity_if_not_allowed

decision_rules:
  accept_if_all_pass: true
  reject_if_any_hard_fail: true
  otherwise: review
```

**These thresholds are examples only.** They are not validated research standards.

### Policy requirements

The policy must clearly distinguish:

- **hard fails**: automatic reject,
- **soft fails**: review required,
- **warnings**: published but not decision-critical.

For example:

| Outcome | Suggested handling |
|---|---|
| Too few trades | hard fail or inconclusive |
| Drawdown exceeds limit | hard fail |
| One metric narrowly misses threshold | review |
| Excessive concentration in top trades | review or reject per policy |

## 8. Decision states

Suggested decision outcomes:

| Decision | Meaning |
|---|---|
| `accept` | Passed all required acceptance rules |
| `reject` | Failed one or more hard acceptance rules |
| `review` | Needs human inspection or broader robustness tests |
| `inconclusive` | Not enough evidence to make an accept/reject claim |

These are **research decisions**, not software-execution statuses.

### Separate execution status

The graph/node status should remain distinct:

| Status | Meaning |
|---|---|
| `diagnostics_ready` | Diagnostics completed and artifacts published |
| `diagnostics_blocked` | Missing prerequisites or incompatible inputs |
| `diagnostics_failed` | Computation or publication failed |

A valid output can therefore be:

```text
status = diagnostics_ready
decision = reject
```

That is a successful diagnostics run with a negative research outcome.

## 9. Metric definitions

The specification must freeze metric definitions.

### Expectancy per trade

\[
E = \frac{\sum_{i=1}^{N} \text{net\_pnl}_i}{N}
\]

### Profit factor

\[
PF = \frac{\sum \text{profits}}{|\sum \text{losses}|}
\]

when total losses are nonzero.

If no losses exist, the policy must define whether profit factor becomes:

- null,
- infinity,
- or a blocked edge case.

### Maximum drawdown

Computed from the equity curve:

\[
DD_t = \frac{Peak_t - Equity_t}{Peak_t}
\]

\[
MaxDD = \max_t DD_t
\]

The equity curve definition must match the backtest engine’s published accounting convention.

### Concentration metric

A useful MVP metric is:

\[
\text{Top-}k\text{ share}
=
\frac{\sum_{i \in \text{top }k \text{ trades}} \text{positive net pnl}_i}{\sum_{i: \text{net pnl}_i > 0} \text{net pnl}_i}
\]

This quantifies dependence on a small number of winners.

## 10. Regime-conditional diagnostics

If the signal and backtest bundles preserve regime context or joinable keys, diagnostics may compute conditional summaries such as:

- trade count by regime,
- win rate by regime,
- expectancy by regime,
- drawdown contribution by regime.

### Important restriction

These diagnostics are descriptive only in the MVP.

They must not:

- alter the regime allowlist,
- suggest a new filtered strategy inside the same run,
- trigger automatic recalibration.

Any proposed regime-based redesign becomes a **new research iteration**.

## 11. Temporal segmentation

The agent should support segmented diagnostics across:

- early vs late test windows,
- monthly or quarterly buckets,
- equal-trade-count buckets,
- drawdown episodes,
- consecutive-win/loss clusters.

This helps detect fragility and temporal clustering.

### Restrictions

Temporal segmentation is evidence, not selection input.

The Diagnostics Agent must not relabel one good subperiod as the “true evaluation period.”

## 12. Data integrity checks inside diagnostics

Even though upstream artifacts were verified, diagnostics should still perform consistency checks on the loaded contents:

- unique trade IDs
- monotonic equity timestamps
- no missing required trade fields
- trades consistent with summary totals within tolerance
- cumulative realized P&L consistent with equity decomposition
- no non-finite metric inputs
- no duplicated rows introduced during joins

If these fail, the agent should return `diagnostics_failed` or `diagnostics_blocked` depending on where the failure occurred.

## 13. Output artifacts

Required bundle:

```text
diagnostics-bundles/<bundle_id>/
├── diagnostics-summary.json
├── diagnostics-metrics.parquet
├── acceptance-decision.json
├── diagnostics-report.json
├── diagnostics-policy.json
└── manifest.json
```

### `diagnostics-summary.json`

Contains top-level metrics and grouped summaries suitable for reporting.

### `diagnostics-metrics.parquet`

One row per metric or metric segment, with fields like:

| Column | Meaning |
|---|---|
| `metric_id` | Stable metric name |
| `segment_type` | overall / monthly / regime / drawdown / etc. |
| `segment_key` | The segment label |
| `value` | Metric value |
| `units` | Currency, fraction, count, bars, etc. |
| `is_pass` | Nullable boolean if tied to acceptance rule |
| `severity` | info / warning / hard_fail |

### `acceptance-decision.json`

Contains:

- overall decision
- hard-fail reasons
- soft-fail reasons
- warning list
- policy identity
- timestamps
- lineage to backtest bundle

### `diagnostics-report.json`

Narrative-oriented machine-readable summary, including:

- execution context
- key findings
- limitations
- suspicious concentration
- acceptance rationale
- next recommended stage

This file is for downstream reporting, not human prose generation alone.

## 14. State updates

Conceptual successful update:

```python
{
    "status": "diagnostics_ready",
    "diagnostics_bundle_ref": "...",
    "diagnostics_manifest_sha256": "...",
    "research_decision": "accept|reject|review|inconclusive",
}
```

These are proposed names, not verified repository fields.

### Routing implication

The Reporting Agent may run only if:

```text
diagnostics_ready
AND diagnostics manifest verifies
```

It may report any valid research decision, including rejection.

## 15. Reliability and determinism

Required rules:

- same verified inputs + same policy + same implementation = same decision
- no random resampling in MVP
- stable sorting for top-trade concentration metrics
- explicit numeric tolerances for reconciliation checks
- no mutation of upstream artifacts
- complete publication or no accepted bundle

Retry must not create conflicting accepted diagnostics bundles for the same logical identity.

### Logical identity

The diagnostics bundle identity should include:

- backtest manifest hash
- diagnostics policy hash
- implementation version
- fold and partition identity
- optional segmentation configuration hash

## 16. Failure handling

Examples of `diagnostics_blocked`:

- missing backtest bundle
- wrong fold or generation
- unsupported artifact schema
- integrity mismatch

Examples of `diagnostics_failed`:

- artifact verified but unreadable due to corruption during local load
- metric computation error
- publication interrupted
- inconsistent trade/equity arithmetic beyond tolerance

Again, **reject** is not a failure state. It is a valid research outcome.

## 17. Acceptance tests

Minimum tests:

| Test | Expected outcome |
|---|---|
| Valid reference backtest | `diagnostics_ready` with deterministic decision |
| Wrong fold or generation | Block |
| Modified trade ledger | Integrity failure |
| Missing trade column | Fail/block according to contract |
| Equity not monotonic in time | Fail |
| Profit factor edge case with zero losses | Policy-defined behavior |
| Summary inconsistent with trades | Fail |
| Too few trades | Reject or inconclusive per policy |
| Max drawdown exceeds limit | Reject |
| Top-trade concentration too high | Review or reject per policy |
| Regime segmentation requested without compatible context | Block or omit per configuration |
| Interrupted publication | No consumable partial diagnostics bundle |
| Retry | No conflicting bundle |
| Any valid negative result | `diagnostics_ready` plus non-accept decision |

## 18. Proposed package structure

```text
diagnostics_phase/
├── pyproject.toml
├── configs/
│   └── diagnostics-policy-v1.yaml
├── src/trading_diagnostics/
│   ├── contracts.py
│   ├── inputs.py
│   ├── metrics.py
│   ├── segmentation.py
│   ├── policy.py
│   ├── reconciliation.py
│   ├── artifacts.py
│   ├── node.py
│   └── __main__.py
└── tests/
```

Suggested interfaces:

```python
load_verified_backtest_bundle(...)
reconcile_backtest_artifacts(...)
compute_diagnostics_metrics(...)
evaluate_acceptance_policy(...)
publish_diagnostics_bundle(...)
load_verified_diagnostics_bundle(...)
diagnostics_agent(state, ...)
```

## 19. UI and reporting updates

### Research Control Center

Add a **Run diagnostics** operation that shows:

- selected backtest bundle
- diagnostics policy
- segmentation options
- expected outputs
- acceptance result
- downloadable artifacts

Display independently:

```text
Backtest integrity
Diagnostics readiness
Acceptance decision
Reporting readiness
Research acceptance outcome
```

### Reporting layer expectations

The Reporting Agent should consume diagnostics artifacts and render:

- summary tables,
- drawdown highlights,
- concentration warnings,
- regime-conditioned summaries,
- final decision and rationale.

It must not recompute diagnostic metrics independently.

## 20. Documentation changes

Update these artifacts:

| Artifact | Required change |
|---|---|
| Architecture | Backtest → Diagnostics → Reporting flow |
| Backtest spec | Clarify diagnostics consumes frozen artifacts |
| Acceptance-policy contract | Define decision semantics and severities |
| Reporting spec | Separate presentation from metric computation |
| Artifact schemas | Define diagnostics files and metric tables |
| UI spec | Add diagnostics workflow and decision display |
| CI | Add reconciliation, decision, and artifact tests |

## 21. Implementation milestones

1. Finalize diagnostics policy schema.
2. Implement trade/equity reconciliation.
3. Implement deterministic metric library.
4. Implement segmented diagnostics.
5. Implement decision engine.
6. Implement artifact publication and verified loading.
7. Integrate graph routing and reporting consumption.

**Definition of done:** the Diagnostics Agent consumes verified backtest outputs, computes deterministic research diagnostics, applies a frozen acceptance policy, and publishes a reproducible decision bundle that supports reporting without altering the underlying simulation.
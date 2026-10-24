# Calibration Agent Specification

**The Calibration Agent selects trading thresholds from verified signal scores using training data, checks the frozen selection against a separate validation gate, and publishes a versioned parameter bundle for backtesting.** It must never use held-out test performance to select or revise parameters.

**Specification:** `calibration-agent-v0.1.0`  
**Status:** Proposed implementation contract—not implemented, repository-verified, or tested. This response contains the specification, not a downloadable extension.

## Purpose and boundaries

The agent answers:

> “Within the approved search space and research budget, which threshold configuration satisfies the training-selection rules and the predeclared validation requirements?”

The MVP should use deterministic Python and a bounded grid search.

| Component | Responsibility |
|---|---|
| Signal Agent | Causal features, continuous scores, eligibility masks |
| **Calibration Agent** | Candidate generation, training-only selection, frozen validation, parameter publication |
| Shared evaluation engine | Position lifecycle, fills, costs, and performance accounting |
| Backtest Agent | Held-out evaluation using frozen parameters and the same execution semantics |
| Diagnostics Agent | Robustness, uncertainty, failure analysis, and research acceptance evidence |
| Strategy Supervisor | Authorization, research budgets, iteration control, and routing |

**`calibration_ready` means an accepted parameter bundle is available. It does not mean the strategy is profitable, robust, or approved for trading.**

## Pipeline placement

```text
Verified Signal Bundle
         │
         ▼
Calibration Agent
┌─────────────────────────────────────┐
│ Verify inputs and partition access  │
│ Freeze search and evaluation rules  │
│ Evaluate candidates on training     │
│ Select one candidate                │
│ Evaluate it once on validation      │
│ Validate and publish parameters     │
└──────────────────┬──────────────────┘
                   │
            calibration_ready
                   │
                   ▼
             Backtest Agent
       Frozen held-out evaluation
                   │
                   ▼
            Diagnostics Agent
```

Training and validation evaluations require simulation. Therefore, the Calibration Agent must call a **shared evaluation engine**, rather than implement a different simulator from the Backtest Agent.

Until that shared engine and its contracts exist, implement candidate generation and selection against a test evaluator. Do not claim production calibration readiness.

## MVP scope

### Included

- One instrument per calibration job
- One frozen signal variant per job
- Explicit training, validation, and held-out intervals
- A finite, predeclared threshold grid
- Deterministic candidate evaluation and selection
- Fixed execution, risk, and cost assumptions
- A single frozen validation check
- Complete candidate and rejection evidence
- Verified parameter publication

A multi-instrument request should create explicitly identified child jobs. The MVP does not perform pooled portfolio calibration.

### Excluded

- Changing Signal Agent feature windows
- Reclassifying regimes
- Discovering regime filters from validation performance
- Bayesian or evolutionary optimization
- Joint optimization of entries, exits, stops, and position sizing
- Automatic retraining after validation rejection
- Selecting parameters from held-out results
- Live trading or broker execution

Any future expansion of the search space must create a new specification version and count toward the research budget.

## Input prerequisites

| Input | Required verification |
|---|---|
| Signal bundles | Supported schemas, hashes, lineage, and `signal_ready` evidence |
| Approved market data | Price coverage required by the evaluation engine |
| Partition plan | Explicit intervals, roles, and permitted uses |
| Strategy configuration | Score sign, threshold meaning, exits, eligibility behavior |
| Evaluation configuration | Shared engine version, fills, costs, sizing, accounting |
| Search configuration | Frozen candidates, objective, constraints, tie-break rules |
| Execution context | Matching request, run, generation, fold, and instrument |
| Authorization | Calibration permitted; research budget available |

### Partition-use enforcement

The reader must distinguish:

```text
training   → candidate evaluation and selection allowed
validation → frozen-candidate gate only
held_out   → unavailable to calibration
```

A filename or `partition_id` column alone is insufficient. The control layer must enforce which artifacts and outcomes the calibration process may access.

For a local trusted-repository MVP, this can be application-level enforcement. It must not be described as operating-system isolation.

## Partition and causality contract

Use half-open intervals:

```text
Training:   [train_start, train_end)
Validation: [validation_start, validation_end)
Held-out:   [test_start, test_end)
```

Require:

```text
train_end <= validation_start
validation_end <= test_start
```

### Feature context versus outcomes

Earlier observations may support causal feature warm-up across a partition boundary.

However:

- Training trade outcomes must not extend into validation.
- Validation trade outcomes must not extend into held-out data.
- Training selection cannot depend on validation prices, fills, or returns.
- Validation results cannot alter the selected candidate.
- Held-out outcomes cannot influence either selection or validation.

### Boundary policy

Freeze a boundary rule before evaluation.

For the MVP:

- Start each evaluation partition flat.
- Do not carry positions across selection boundaries.
- Stop opening new positions sufficiently early for the declared maximum holding period.
- Close remaining positions using a predeclared, executable boundary rule.
- Include all liquidation costs.
- Block the evaluation if the required closing observation is unavailable.

Do not merely truncate open trades and omit their losses or costs.

### Event overlap

If later versions introduce forward-return targets or cross-validation, selection rules must account for overlapping outcome intervals—not just row timestamps.

An arbitrary number of “gap rows” must not be presented as proof that information leakage has been eliminated.

## Candidate definition

The proposed MVP searches **only the symmetric entry threshold**.

Given the Signal Agent convention:

```text
positive score → long-oriented opportunity
negative score → short-oriented opportunity
```

For threshold `theta`:

```text
eligible and score >= theta   → long-entry intent
eligible and score <= -theta  → short-entry intent
otherwise                    → no new entry intent
```

Require:

```text
theta > 0
```

These intents are not fills.

### Fixed strategy semantics

The configuration must also define, without searching:

- Long and short permissions
- Exit conditions
- Maximum holding period
- Position size and instrument specifications
- Maximum concurrent positions
- Whether direct reversal is allowed
- What happens when a row becomes ineligible
- Session and partition-end behavior

For an initial MVP, use:

```text
one position per instrument
no pyramiding
no direct reversal
no re-entry on the same decision event after exit
```

An ineligible signal prevents new entry. It does not automatically close an existing position unless the frozen strategy explicitly requires that behavior.

## Search configuration

Illustrative configuration:

```yaml
schema_version: "1.0"
calibrator_id: "bounded_entry_grid_v1"

scope:
  instruments_per_job: 1
  signal_variant_policy: "frozen"

search:
  parameter: "symmetric_entry_threshold"
  candidates: [0.5, 1.0, 1.5, 2.0]
  maximum_unique_candidates: 4

selection:
  source_partition: "training"
  objective: "net_return_on_initial_capital"
  direction: "maximize"
  tie_break: "lowest_threshold"

constraints:
  minimum_closed_trades: 30
  maximum_equity_drawdown: 0.20

validation:
  mode: "single_frozen_candidate"
  minimum_closed_trades: 10
  minimum_net_return: 0.0
  maximum_equity_drawdown: 0.20
  failure_action: "reject"

evaluation:
  engine_config_ref: "configs/evaluation-v1.json"
  strategy_execution_ref: "configs/position-rules-v1.json"

publication:
  require_validation_acceptance: true
```

**The candidate values and acceptance limits above are illustrative engineering settings, not validated trading parameters.**

Configuration references must be resolved, content-hashed, and validated before evaluation. Arbitrary import paths, executable expressions, and shell commands are prohibited.

## Shared evaluation engine

The Calibration and Backtest Agents must use the same versioned execution implementation.

### Required assumptions

| Area | Explicit contract |
|---|---|
| Decision timing | Earliest use of each score and required context |
| Entry timing | First permitted execution event after the decision |
| Exit timing | Same causal ordering rules as entries |
| Costs | Commission, fees, spread, slippage, and units |
| Sizing | Fixed quantity or another frozen rule |
| Instrument | Tick size, multiplier, currency, supported price representation |
| Accounting | Initial capital, mark-to-market equity, realized/unrealized P&L |
| Constraints | Position limits, margin/capital handling, invalid-price behavior |
| Missing data | Behavior when a required execution observation is unavailable |

### Timestamp ties

Do not resolve equal timestamps implicitly.

The engine must define event ordering for situations such as:

```text
previous bar closes at 10:00
next bar opens at 10:00
```

A same-timestamp fill is permitted only if the declared event ordering and latency assumptions support it. Otherwise, use a later event.

### Cost consistency

Search objectives and validation must include the same declared cost model.

For futures, calculate P&L using the instrument’s declared point value and currency model—not an unspecified percentage-price approximation.

## Objective and constraints

### Training objective

For the MVP:

\[
R_{\text{net}} =
\frac{E_{\text{end}}-E_{\text{start}}}{E_{\text{start}}}
\]

where equity includes declared transaction costs and the specified liquidation treatment.

Evaluate every candidate on the same training interval, initial capital, and sizing rules.

### Feasibility first

A candidate is selectable only if it:

- Completes evaluation successfully
- Satisfies minimum trade requirements
- Meets the drawdown constraint
- Produces finite metrics
- Respects capital and execution rules

Then rank feasible candidates by the frozen objective.

### Drawdown definition

Use the marked-to-market equity series, including unrealized P&L, at the declared valuation frequency.

The configuration must state what happens if equity becomes nonpositive. Do not let undefined ratios silently become valid metrics.

### Tie handling

Apply a deterministic tie-break rule using a declared comparison tolerance.

For this MVP, candidates within that tolerance use the lowest threshold. This is reproducibility policy, not a claim that a lower threshold is economically preferable.

## Selection procedure

```text
Verify and freeze inputs
          │
          ▼
Generate unique, ordered candidates
          │
          ▼
Evaluate each on training only
          │
          ▼
Apply training feasibility constraints
          │
     ┌────┴──────────┐
     │               │
No feasible      Feasible candidates
candidate            │
     │               ▼
     │         Select one winner
     │               │
     │         Freeze selection
     │               │
     │               ▼
     │         Validate once
     │          ┌────┴─────┐
     │          │          │
     ▼        Reject     Accept
No candidate    │          │
                ▼          ▼
             Evidence   Publish bundle
```

### No-candidate behavior

If no candidate is feasible:

- Publish diagnostic evidence.
- Set `calibration_no_candidate`.
- Do not silently choose the “least bad” candidate.
- Do not expand the search automatically.
- Do not invoke the Backtest Agent.

A legitimate no-candidate outcome is not a software crash.

## Validation gate

Evaluate only the frozen training winner against the predeclared validation requirements.

### Mandatory restrictions

- Do not evaluate all candidates on validation and choose the best.
- Do not replace a rejected winner with the runner-up.
- Do not change trade-count requirements after observing results.
- Do not search for a more favorable validation interval.
- Do not overwrite rejected evidence with a later accepted run.

If validation rejects the winner, return `calibration_rejected`.

### Reuse of validation data

Any later strategy change informed by validation outcomes makes that validation interval part of the development process.

A subsequent iteration must record that fact. It cannot continue describing the same interval as untouched confirmation.

Held-out failures must not trigger automatic retuning against the same held-out period.

## Budget and iteration control

Keep three counters separate:

| Counter | Meaning |
|---|---|
| Calibration round | Supervisor-authorized logical search operation |
| Candidate trial | Unique candidate evaluation under a fixed input/evaluation identity |
| Execution attempt | Technical attempt, including retries |

### Budget rules

- Reserve the round before candidate evaluation begins.
- A started round consumes its logical allocation even if it fails or finds no candidate.
- Technical retries retain the round and candidate identities.
- Retry attempts still count toward compute/runtime budgets.
- Changing signals, candidates, costs, or execution rules requires a new logical search identity.
- Cancellation does not erase consumed budget.
- The Calibration Agent cannot authorize another round.

The supervisor’s earlier `max_iterations` limit must be mapped explicitly to calibration rounds; it must not be interpreted as the number of candidate thresholds.

Maintain a run-wide trial ledger so repeated small searches cannot conceal the total search effort.

## Output artifacts

### Accepted bundle

```text
calibration-bundles/<bundle_id>/
├── selected-parameters.json
├── candidate-results.parquet
├── validation-result.json
├── calibration-report.json
├── calibration-config.json
├── evaluation-config.json
└── manifest.json
```

### Selected parameters

Include:

- Selected threshold
- Score comparison convention
- Strategy execution configuration identity
- Signal variant identity
- Instrument and fold
- Selection and validation interval identities
- Training objective and feasibility evidence
- Validation decision
- Parameter effective time
- Upstream and implementation hashes

The parameter effective time must be no earlier than the availability of the completed validation evidence used to approve it.

### Candidate results

One row per candidate, including rejected and failed trials:

| Field | Meaning |
|---|---|
| `candidate_id` | Stable candidate identity |
| `parameters` | Exact searched values |
| `status` | Evaluated, infeasible, or failed |
| `training_objective` | Nullable when unavailable |
| `closed_trade_count` | Training count |
| `maximum_drawdown` | Declared equity drawdown |
| `total_cost` | Cost amount and declared units |
| `rejection_reasons` | Structured reasons |
| `evaluation_ref` | Detailed engine evidence |
| `attempt_count` | Technical execution attempts |

Retain trade/equity evidence through hashed references when too large for the primary bundle.

### Rejected outcomes

Store no-candidate, validation rejection, and failure evidence outside the approved-parameter namespace.

A partial search cannot publish an approved winner unless an explicitly versioned future policy permits partial searches. The MVP requires the full declared candidate set.

## State and routing

| Status | Meaning |
|---|---|
| `calibration_ready` | Parameters passed the frozen validation gate and were published |
| `calibration_no_candidate` | No feasible training candidate |
| `calibration_rejected` | Frozen winner failed validation |
| `calibration_blocked` | Missing prerequisites, authorization, or budget |
| `calibration_failed` | Evaluation or publication error |

Running progress belongs in worker events or another durable progress mechanism.

Conceptual success update:

```python
{
    "status": "calibration_ready",
    "calibration_bundle_ref": "...",
    "calibration_manifest_sha256": "...",
    "selected_candidate_id": "...",
    "calibration_round_id": "...",
}
```

These are proposed fields, not verified repository APIs.

### Routing invariant

```text
Backtest may start only if:

calibration_ready
AND selected parameter bundle verifies
AND active fold and generation match
AND parameter effective time is compatible
AND held-out evaluation is separately authorized
```

On any unsuccessful outcome, clear stale approved-parameter references.

## Reliability requirements

- No runtime provider-network access in the MVP
- Bounded candidate count, memory, runtime, and evidence size
- Cancellation checks between evaluations and inside long engine work
- Deterministic candidate ordering
- Persisted trial and attempt identities
- Atomic publication of complete bundles
- Integrity verification before cache reuse
- No silent selection from an incomplete search
- No automatic retries of deterministic policy failures
- No claim of exactly-once execution

A crash after simulation but before result persistence must not produce conflicting candidate evidence on resume.

## Acceptance tests

| Test | Required outcome |
|---|---|
| Valid reference inputs | Accepted bundle or legitimate declared rejection |
| Held-out artifact requested by calibration | Access denied |
| Training outcomes cross validation boundary | Reject evaluation scope |
| Validation outcomes cross test boundary | Reject evaluation scope |
| Wrong fold, generation, or signal variant | Block |
| Modified signal or evaluation config | Integrity/identity failure |
| Threshold equality | Matches documented entry comparisons |
| Ineligible signal | No new entry; fixed position policy respected |
| Equal objective values | Deterministic tie-break |
| Costs changed | New evaluation identity and recomputation |
| Too few training trades | Candidate infeasible |
| No feasible candidates | `calibration_no_candidate` |
| Validation rejects winner | No runner-up substitution |
| Test prices changed | Training selection and validation decision unchanged |
| Validation prices changed | Training winner unchanged |
| Candidate evaluation fails | No silent omission or partial winner |
| Repeated technical retry | Same logical trial; attempts recorded |
| Budget exhausted | Block before additional evaluation |
| Interrupted publication | No approved partial bundle |
| Any blocked/rejected outcome | Backtest spy is never invoked |
| Shared-engine replay | Calibration and Backtest reproduce equivalent execution under identical inputs |

The shared-engine replay test is essential: it detects situations where calibration appears attractive only because its simulator differs from the final backtest.

## Proposed package structure

```text
calibration_phase/
├── pyproject.toml
├── configs/
│   └── bounded-entry-grid-v1.yaml
├── src/trading_calibration/
│   ├── contracts.py
│   ├── inputs.py
│   ├── candidates.py
│   ├── evaluation.py
│   ├── selection.py
│   ├── validation.py
│   ├── budgets.py
│   ├── artifacts.py
│   └── node.py
└── tests/
```

Proposed interfaces:

```python
load_verified_calibration_inputs(...)
validate_search_config(...)
reserve_calibration_round(...)
generate_candidates(...)
evaluate_training_candidate(...)
select_training_winner(...)
validate_frozen_candidate(...)
publish_calibration_bundle(...)
load_verified_parameters(...)
calibration_agent(state, ...)
```

The evaluation module is an adapter to the shared engine—not a second execution implementation.

## UI and documentation updates

### Research Control Center

Add a **Calibrate thresholds** operation with:

- Verified signal bundle selection
- Instrument and fold scope
- Training/validation interval preview
- Candidate grid preview
- Fixed cost and execution assumptions
- Remaining round and trial budgets
- Explicit confirmation before starting

Show separate indicators:

```text
Input integrity
Training search completion
Candidate feasibility
Validation decision
Parameter bundle integrity
Backtest authorization
Research acceptance: Not evaluated
```

Candidate leaderboards must be labelled **Training results**. Validation should show the frozen winner only.

Do not expose held-out performance in the calibration-selection view.

### Required specification updates

| Artifact | Required change |
|---|---|
| Architecture | Add training evaluation through the shared engine |
| Supervisor | Define budgets, round reservations, and retuning restrictions |
| Signal contract | Clarify partition scope and score interpretation |
| Regime contract | Require causal regime context for selection partitions |
| Backtest specification | Consume frozen parameters and reuse engine semantics |
| Artifact contracts | Define candidate, selection, validation, and budget lineage |
| CI | Add isolation, boundary, replay, rejection, and budget tests |
| UI | Separate search success, validation acceptance, and research approval |

## Implementation milestones

1. Finalize partition, execution, and budget contracts.
2. Build and verify the shared evaluation engine.
3. Implement bounded candidate generation.
4. Implement training feasibility and deterministic selection.
5. Add frozen validation and no-candidate handling.
6. Add trial ledger, publication, and verified parameter loading.
7. Integrate graph routing, UI, and CI.

**Definition of done:** calibration selects parameters using training only, applies a frozen validation gate without fallback tuning, records the complete search effort, and releases a verifiable parameter bundle that the Backtest Agent can execute under identical semantics without accessing held-out outcomes during selection.
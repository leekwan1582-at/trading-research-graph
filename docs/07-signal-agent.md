# Signal Agent Specification

**The Signal Agent converts verified market data and regime context into causal features and continuous opportunity scores for the Calibration Agent.** It does **not** optimize trading thresholds, simulate trades, or approve a strategy.

**Specification:** `signal-agent-v0.1.0`  
**Status:** Proposed implementation contract. Repository compatibility has not been verified; this is not an implemented or tested extension.

## Purpose and boundaries

The agent answers:

> “Using only information available at this decision point, what measurable trading opportunity does the declared strategy identify?”

The first version should be deterministic Python—not an LLM-based decision maker.

| Component | Owns |
|---|---|
| Data Agent | Approved market data and quality evidence |
| Regime Agent | Causal market-condition classifications |
| Fan-in Barrier | Compatibility, alignment, and readiness of upstream inputs |
| **Signal Agent** | Strategy features, continuous scores, and eligibility reasons |
| Calibration Agent | Threshold selection under declared training/validation rules |
| Backtest Agent | Position lifecycle, fills, costs, and execution simulation |

**Use `signal_ready` to mean the signal artifact is valid—not that its predictive value or profitability has been established.**

## Pipeline placement

```text
Approved Data Bundle
          │
          ▼
     Regime Agent
          │
          ▼
 Fan-in Readiness Gate
   Data + Regime verification
          │
          ▼
      Signal Agent
┌───────────────────────────────┐
│ Verify released inputs        │
│ Resolve strategy specification│
│ Calculate causal features     │
│ Calculate continuous scores   │
│ Apply declared eligibility    │
│ Validate and publish          │
└──────────────┬────────────────┘
               │
          signal_ready
               │
               ▼
       Calibration Agent
               │
               ▼
         Backtest Agent
```

The initial integration graph should end after the Signal Agent until calibration exists.

There must be no direct Data → Signal or Regime → Signal route that bypasses the verified Fan-in release.

## MVP scope

### Included

- One versioned strategy plugin per signal variant
- Per-instrument trailing features
- Continuous, signed opportunity scores
- Verified regime context
- Explicit warm-up and exclusion reasons
- Fold and partition identity
- Immutable output artifacts and lineage
- Reproducibility and causality tests

### Excluded

- Threshold search or parameter optimization
- Entry/exit orders
- Position sizing and portfolio construction
- Stop-loss, take-profit, or holding-period simulation
- Transaction-cost or P&L calculations
- Forward-return targets in production signal artifacts
- Automatically selected regime filters
- Supervised-model fitting in the first version
- Automatic modification of strategy rules

A new feature window or formula is a new **signal variant**, not an undocumented calibration change.

## Input prerequisites

The Signal Agent must load inputs through a verified reader, not trust status strings or file paths alone.

| Required input | Verification |
|---|---|
| Fan-in release | Decision is `ready`; manifest and report hashes match |
| Execution context | Run, generation, request, execution plan, and fold match |
| Approved data | Quality approval and integrity evidence remain valid |
| Regime bundle | References the exact consumed data bundle |
| Strategy specification | Supported version; frozen content hash |
| Partition scope | Explicit interval, partition role, and permitted use |
| Authorization | Current operation permits signal preparation |

### Authorization separation

Generating signals does not authorize calibration or backtesting.

The agent must preserve the existing supervisor’s execution boundary. It cannot convert `plan_only` into an executable research run.

### Partition compatibility

The earlier Regime specification emits classifications for an inference interval. **Do not assume that this automatically supplies regime-aware calibration inputs for the training interval.**

Where a strategy requires regime context:

- Each required partition needs an appropriate verified release.
- Training-period regime context must satisfy its own causal fitting rules.
- Thresholds fitted using later training observations must not be retrospectively applied as if available earlier.
- Out-of-fold or expanding-history regime preparation is a separate orchestration responsibility.
- Missing compatible context blocks the partition; the Signal Agent must not manufacture it.

A strategy explicitly designed to ignore regimes may use `regime_usage: context_only`, subject to the upstream release policy.

## Input data contract

Required conceptual fields:

| Field | Meaning |
|---|---|
| `instrument` | Stable instrument identity |
| `bar_close_at` | Canonical UTC bar-closing timestamp |
| `available_at` | Earliest historical availability under the approved model |
| `close` | Finite price in the declared representation |
| Continuity metadata | Identifies unsupported breaks |
| Regime fields | Classification, availability, and threshold-set identity |
| Eligibility information | Masks and reasons released by the barrier |

The canonical key is:

```text
(instrument, bar_close_at)
```

Requirements:

- Keys are unique.
- Rows are ordered within each instrument.
- No implicit nearest-time joins.
- No silent resampling.
- No mixing adjusted and unadjusted price representations.
- No forward filling across unsupported gaps.
- Historical context outside the requested output interval is explicitly identified.

The minimum necessary price constraints depend on the strategy plugin. A price-level deviation calculation does not inherently require strictly positive prices; another upstream component may still impose that limitation.

## Strategy configuration

An illustrative MVP configuration:

```yaml
schema_version: "1.0"
strategy_id: "trailing_price_deviation"
strategy_version: "1.0.0"
signal_variant_id: "price-deviation-n20-v1"

price_field: "close"

features:
  baseline_window: 20
  baseline_includes_current_bar: false
  standard_deviation_ddof: 1
  zero_variance_policy: "ineligible"

score:
  convention: "positive_long_negative_short"
  transform: "negative_zscore"
  clipping: "none"

regime:
  usage: "context_only"
  allowed_labels: []

continuity:
  unsupported_gap_action: "reset"

output:
  preserve_requested_rows: true
  minimum_eligible_rows_per_instrument: 1
```

**The 20-bar window is an engineering example, not a validated trading parameter.**

### Regime modes

| Mode | Behavior |
|---|---|
| `context_only` | Preserve regime context without using the label as a score filter |
| `filter` | Require classification and membership in an explicit allowlist |

Rules:

- Under `filter`, `allowed_labels` must be nonempty.
- The allowlist must be frozen before evaluating the target partition.
- The agent must not discover profitable regimes and silently update the allowlist.
- Upstream eligibility restrictions always apply, including under `context_only`.

### Configuration validation

Reject unknown keys and unsupported versions.

Require a baseline window of at least two observations, valid standard-deviation settings, supported transforms, and a declared continuity policy.

A zero or near-zero variance tolerance, if used, must be explicit, unit-aware, and versioned.

## Feature and score definitions

For the example strategy, calculate independently within each instrument and continuity segment.

### Prior-window baseline

At bar \(t\), use the previous \(N\) eligible prices, excluding the current bar:

\[
\mu_t = \frac{1}{N}\sum_{i=t-N}^{t-1}C_i
\]

\[
s_t =
\sqrt{
\frac{1}{N-1}
\sum_{i=t-N}^{t-1}(C_i-\mu_t)^2
}
\]

This requires \(N\) previous prices plus the current price to produce the first score.

### Deviation score

\[
z_t = \frac{C_t-\mu_t}{s_t}
\]

\[
\text{raw\_score}_t = -z_t
\]

Interpretation:

| Raw score | Declared interpretation |
|---|---|
| Positive | Price is below its trailing baseline; long-oriented opportunity score |
| Negative | Price is above its trailing baseline; short-oriented opportunity score |
| Zero | Price equals its trailing baseline |
| Null | Score cannot be calculated under the contract |

This interpretation is a strategy hypothesis, not a probability forecast or evidence of mean reversion.

### Edge-case policy

- Insufficient history → null score, ineligible
- Zero variance → null score, ineligible
- Unsupported gap → reset history, then warm up
- Non-finite required input → block or fail input verification
- Non-finite computed result → fail output validation
- Regime exclusion → preserve a valid raw score but mark it ineligible

**Never replace an unavailable score with zero.** Zero is a meaningful calculated result.

## Eligibility semantics

Keep numerical validity separate from permission to use the score.

```text
eligible =
    feature_ready
    AND upstream_eligible
    AND regime_filter_passed_if_enabled
    AND row_is_inside_requested_output_scope
```

Proposed reason codes:

```text
insufficient_history
gap_reset_warmup
zero_variance
upstream_masked
regime_unknown
regime_not_allowed
```

Use an ordered list of reasons when multiple restrictions apply.

### Ineligible is not an exit

An ineligible row means:

> “Do not create a new decision from this score.”

It does **not** mean:

```text
Close an existing position immediately.
```

Position behavior during unknown regimes, missing observations, or blocked entries belongs in the declared calibration/backtest contract.

Preserve requested rows and masks rather than dropping them.

## Causality and availability

### Availability fields

Publish two separate timestamps:

| Field | Meaning |
|---|---|
| `score_available_at` | Latest required price/feature information availability |
| `decision_available_at` | Latest availability of the score and any context required to use it |

For the MVP, use a conservative decision time that includes the relevant upstream context.

Do not confuse historical availability with the wall-clock time when the batch artifact was written.

### Required rules

- Trailing calculations only; no centered windows.
- No backward filling.
- No whole-dataset normalization.
- No future-return information in score construction.
- No test-period information used to select windows or filters.
- No resetting history simply because a train/validation boundary was crossed.
- Earlier permissible history may support warm-up.
- Prior observations within an inference period may support later rolling features.
- Same-bar score availability does not guarantee a same-bar executable fill.

### Prefix invariance

With configuration and upstream identities appropriately fixed:

> Appending or changing future observations must not change earlier features, scores, eligibility, or decision timestamps.

Where upstream regime artifacts change version because future data was appended, the test must compare equivalent earlier regime content rather than require unchanged whole-file hashes.

## Output contract

### Signal table

Publish `signals.parquet`.

| Column | Requirement |
|---|---|
| `instrument` | Canonical instrument identifier |
| `bar_close_at` | Canonical input bar key |
| `partition_id` | Declared output partition |
| `baseline_mean` | Nullable during warm-up |
| `baseline_std` | Nullable during warm-up |
| `deviation_zscore` | Nullable when unavailable |
| `raw_score` | Continuous signed score |
| `feature_ready` | Numerical prerequisites satisfied |
| `upstream_eligible` | Barrier-provided eligibility |
| `regime_filter_passed` | Result under declared regime policy |
| `eligible` | Final row usability |
| `ineligible_reasons` | Empty when eligible |
| `regime_label` | Preserved upstream context |
| `score_available_at` | Historical score availability |
| `decision_available_at` | Historical decision availability |
| `signal_variant_id` | Frozen variant identity |

The MVP must not publish columns that imply trading decisions, such as:

```text
entry_order
position_size
fill_price
realized_pnl
```

### Row-preservation requirements

- Exactly one output row per requested input key.
- Context-only warm-up rows outside output scope are not emitted as decision rows.
- Valid scores remain finite.
- Eligible rows cannot have null scores.
- Output order is deterministic.
- No cross-instrument rolling contamination.

## Artifact bundle

```text
signal-bundles/<bundle_id>/
├── signals.parquet
├── signal-report.json
├── strategy-config.json
└── manifest.json
```

### Signal report

Include:

- Contract and implementation versions
- Execution, generation, fold, and partition identities
- Input and output row counts
- Eligible and ineligible counts per instrument
- Reason-code counts
- Finite-score summary statistics
- Warm-up and continuity-reset counts
- Warnings
- Readiness decision
- Upstream lineage

Score summaries are retrospective diagnostics only. They must not feed back into earlier scores.

### Manifest lineage

Bind the bundle to:

```text
request hash
execution-plan hash
barrier release manifest hash
approved data manifest hash
regime manifest hash
strategy configuration hash
signal implementation identity
fold and partition specification
```

The outer manifest hashes the component files. Avoid circular hash references.

Hashes provide integrity relative to trusted references; they do not prove predictive value.

## State and routing

### Proposed statuses

| Status | Meaning |
|---|---|
| `signal_running` | Worker has started the operation |
| `signal_ready` | Output validated and approved bundle published |
| `signal_blocked` | Required inputs, compatibility, or usable coverage are missing |
| `signal_failed` | Computation, validation, or publication failed |

A running indicator may belong in the worker event store rather than graph state; it should not depend on a long-running node returning an intermediate update.

Conceptual successful update:

```python
{
    "status": "signal_ready",
    "signal_bundle_ref": "...",
    "signal_manifest_sha256": "...",
    "signal_report_ref": "...",
}
```

### Routing invariant

```text
Calibration may start only if:

signal_ready
AND signal bundle verifies
AND scope matches the active fold/partition
AND calibration is separately authorized
```

Blocked or failed paths must clear stale successful references.

Signal preparation does not increment the calibration iteration counter.

## Calibration handoff

The Calibration Agent receives **scores and eligibility**, not preselected trade thresholds.

It must independently define and record:

- Which training/validation partitions may influence selection
- Candidate threshold search space
- Minimum observation requirements
- Whether thresholds differ by regime
- Position and exit semantics
- Frozen evaluation behavior for held-out data

The Signal Agent must not include future-return targets in its production bundle. Any calibration target construction belongs in a separate, lineage-tracked component with explicit horizon boundaries.

**A held-out signal bundle may be computed causally, but its outcomes must not become available to threshold selection.** Partition-use restrictions require orchestration and reader enforcement, not just a filename.

## Proposed package interfaces

```text
signal_phase/
├── pyproject.toml
├── configs/
│   └── trailing-price-deviation-v1.yaml
├── src/trading_signal/
│   ├── contracts.py
│   ├── inputs.py
│   ├── features.py
│   ├── scoring.py
│   ├── eligibility.py
│   ├── validation.py
│   ├── artifacts.py
│   ├── node.py
│   └── __main__.py
└── tests/
```

Proposed interfaces—not existing repository APIs:

```python
load_verified_signal_inputs(...)
validate_strategy_config(...)
compute_causal_features(...)
compute_raw_scores(...)
evaluate_eligibility(...)
validate_signal_output(...)
publish_signal_bundle(...)
load_verified_signal_bundle(...)
signal_agent(state, ...)
```

Keep pure numerical calculations separate from file access, authorization, and publication.

No runtime `eval`, arbitrary Python expressions, shell commands, or unapproved plugin imports may come from configuration.

## Reliability requirements

- Freeze configuration before execution.
- Enforce row, memory, runtime, and output-size limits.
- Check cancellation between bounded processing units.
- Keep rolling state correct across chunks.
- Publish atomically through the existing artifact mechanism.
- Verify cached artifacts before reuse.
- Revalidate inputs after resume.
- Avoid conflicting releases after retries.
- Keep diagnostic examples bounded.
- Perform no provider-network access in the MVP.

Logical cache identity must include upstream content, strategy configuration, implementation identity, and output scope.

If reusable numerical content is shared across runs, create a new verified receipt binding it to the current execution.

## Acceptance tests

| Test | Expected outcome |
|---|---|
| Approved reference input | Valid signal bundle |
| Missing or blocked Fan-in release | Block before computation |
| Wrong generation, fold, or partition | Block |
| Modified upstream artifact | Integrity failure |
| Missing causal regime context | Block when required |
| First eligible feature row | Matches the documented prior-window convention |
| Positive/negative deviation | Matches score sign convention |
| Flat prior window | Null score and `zero_variance` |
| Unsupported gap | Reset and explicit warm-up |
| Regime filter exclusion | Raw score retained; eligibility false |
| Unknown regime | Apply frozen upstream/filter policy |
| Future data changed | Earlier outputs unchanged |
| Multiple instruments | No shared rolling state |
| Batch versus chunked processing | Equivalent numerical results within declared tolerance |
| Eligible row with null/non-finite score | Output validation fails |
| All rows ineligible | Block under minimum-coverage policy |
| Some nonzero scores absent | Valid if readiness requirements pass |
| Publication interrupted | No consumable partial bundle |
| Retry or resume | No conflicting release |
| Cancellation | No subsequent calibration execution |
| Any blocking path | Downstream spy is never called |

Use provenance-backed data for integration evidence. Any deliberately constructed boundary-test inputs must be clearly labelled test-only.

Passing these tests establishes implementation behavior—not strategy effectiveness.

## UI and documentation updates

### Research Control Center

Add a **Generate signals** operation with:

- Verified barrier release selection
- Strategy and variant selection
- Fold/partition scope preview
- Immutable configuration preview
- Regression and authorization gates
- Execution logs and evidence downloads

Add a **Signals** panel showing eligible coverage, exclusion reasons, score distributions, availability conventions, and lineage.

Display separately:

```text
Regression gate:       Passed / Failed / Not run
Input integrity:      Verified / Failed
Signal readiness:     Ready / Blocked / Failed
Calibration authority: Granted / Not granted
Research acceptance:  Not evaluated
```

### Artifact updates

| Artifact | Required change |
|---|---|
| Architecture | Add Barrier → Signal → Calibration contract |
| Supervisor plan | Freeze signal variant, partition use, and permissions |
| Regime specification | Clarify availability and training-context obligations |
| Fan-in specification | Declare signal input fields and warm-up context scope |
| Signal contract | Define features, score semantics, masks, and artifacts |
| Calibration specification | Separate score production from threshold selection |
| CI | Add feature, causality, integrity, and routing tests |
| UI specification | Add signal preparation and independent readiness indicators |

## Implementation milestones

1. Agree on upstream adapters and partition contracts.
2. Implement and test pure trailing features.
3. Implement scoring and eligibility.
4. Add causal availability and continuity handling.
5. Add validation, publication, and verified loading.
6. Integrate the graph and failure routing.
7. Connect the UI and CI evidence.

**Definition of done:** approved upstream inputs produce reproducible, causally valid scores and explicit eligibility masks; blocked inputs cannot reach calibration; artifact verification and prefix-invariance tests pass; and no UI or state label presents signal readiness as strategy acceptance.
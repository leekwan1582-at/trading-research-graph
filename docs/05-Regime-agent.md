# Phase 4 — Regime Agent Specification

**The Regime Agent will classify market conditions from quality-approved historical data and publish causal, versioned regime labels for downstream research.** Start with a deterministic classifier—not an LLM or an automatically fitted clustering model.

**Status:** Proposed specification, version `0.1.0`. This is not an implemented extension or downloadable package, and compatibility with your repository has not yet been verified.

## 1. Purpose and scope

The Regime Agent answers:

> “Using only information available at this point in time, what volatility and directional-persistence regime describes this instrument?”

Its output provides context for signal generation, calibration, and diagnostics.

### MVP responsibilities

- Consume an approved Data Agent bundle.
- Verify data-quality evidence, integrity, and request compatibility.
- Calculate trailing, causal regime features.
- Apply training-only volatility thresholds.
- Classify each eligible bar.
- Publish labels, fitted thresholds, diagnostics, and lineage.
- Block downstream execution when required conditions are not satisfied.

### Out of scope

- Generating entry or exit signals
- Selecting regimes based on strategy profitability
- Optimizing thresholds against test-period returns
- Predicting the next market regime
- Automatically repairing rejected market data
- Live trading or order execution
- HMM, clustering, or LLM-based classification in the first version

**A regime label describes the chosen measurements. It is not evidence that a trading strategy will perform well in that regime.**

***

## 2. Architecture and prerequisites

For this version, the Regime Agent depends on completed data preparation. Do **not** execute it in parallel with the Data Agent.

```text
Research Request
       │
       ▼
Strategy Supervisor
       │
       ▼
Data Agent
       │
       ▼
Phase 3.1 Quality Gate
       │
       ├── Reject / Review / Error → Stop
       │
       ▼
Approved Data Bundle
       │
       ▼
Regime Agent
┌──────────────────────────────────┐
│ Verify approved input bundle     │
│              │                   │
│ Resolve classification config    │
│              │                   │
│ Calculate causal features        │
│              │                   │
│ Fit training-only thresholds     │
│              │                   │
│ Classify inference-period bars   │
│              │                   │
│ Validate and publish bundle      │
└──────────────┬───────────────────┘
               │
          regime_ready
               │
               ▼
          Signal Agent
```

### Required upstream conditions

| Requirement | Behavior if missing |
|---|---|
| Data quality decision is `accept` | Block |
| Required quality checks completed | Block |
| Approved data and report hashes match | Block |
| Instruments and bar specification match | Block |
| Training and inference boundaries are explicit | Block |
| Execution authorization permits regime preparation | Block |
| Configured classifier supports the input price representation | Block |

**Phase 3.1 is a dependency, not an assumed completed implementation.** Until its verified-reader contract exists, develop the classifier and contract tests independently; do not advertise end-to-end production readiness.

***

## 3. Classification approach

Use two independent dimensions:

| Dimension | MVP labels | Measurement |
|---|---|---|
| Volatility | `low`, `normal`, `high` | Trailing standard deviation of log returns |
| Directional persistence | `up`, `down`, `non_directional` | Signed movement and efficiency ratio |

The combined label has this format:

```text
direction.volatility
```

Examples:

```text
up.high
down.normal
non_directional.low
```

There are nine possible classified combinations.

**Do not name `non_directional` as `mean_reverting`.** This classifier does not test mean reversion.

### Unclassified rows

Use:

```text
regime_label = unknown
```

with a separate reason, such as:

```text
insufficient_history
gap_reset_warmup
```

Structural errors, unsupported input, and failed integrity checks must block the run rather than being silently converted into `unknown`.

***

## 4. Input contract

### Approved data

The verified input reader must supply:

| Field | Requirement |
|---|---|
| `instrument` | Stable identifier consistent with the request |
| `bar_close_at` | Timezone-aware UTC timestamp |
| `available_at` | Earliest timestamp when the completed bar is usable under the declared availability model |
| `close` | Finite, strictly positive for this MVP |
| Bar specification | Frequency, timestamp convention, calendar, price representation |
| Continuity information | Enough metadata to identify unsupported gaps and valid adjacent observations |

The MVP uses log returns. Consequently, zero or negative prices are unsupported and must cause a clear compatibility failure.

**This does not mean zero or negative prices are universally bad market data.** Supporting such datasets requires a separately specified return definition and classifier version.

### Lineage

Carry these identities into the Regime output:

```text
request hash
approved data manifest hash
data file hash
quality report hash
regime configuration hash
classifier implementation version
```

Hash field names must be mapped to your actual upstream contracts during integration.

### No implicit availability assumption

Do not silently equate a bar’s opening timestamp with its availability.

If source data uses opening timestamps, the approved-data contract must define how closing time and availability are derived.

***

## 5. Configuration contract

An illustrative configuration:

```yaml
schema_version: "1.0"
classifier_id: "causal_volatility_efficiency_v1"

return_method: "log"
volatility_window: 20
volatility_ddof: 1

volatility_thresholds:
  method: "training_quantiles"
  low_quantile: 0.3333333333333333
  high_quantile: 0.6666666666666666
  interpolation: "linear"
  minimum_training_observations: 100
  degenerate_thresholds: "reject"

direction:
  efficiency_window: 20
  efficiency_threshold: 0.30

continuity:
  unsupported_gap_action: "reset"

output:
  preserve_inference_rows: true
  minimum_classified_rows_per_instrument: 1
  unknown_policy: "allow_warmup_only"
```

**These numbers are proposed engineering defaults, not empirically validated trading parameters.**

The request must separately define:

```text
fit_start
fit_end
inference_start
inference_end
```

Use half-open intervals:

```text
Training:  [fit_start, fit_end)
Inference: [inference_start, inference_end)
```

Require:

```text
fit_end <= inference_start
```

Do not invent missing boundaries from the overall historical date range.

### Configuration validation

Reject:

- Unsupported schema or classifier versions
- Invalid windows or quantile ordering
- Nonpositive minimum sample requirements
- Efficiency thresholds outside `(0, 1]`
- Overlapping training and inference periods
- Missing instruments
- Unsupported continuity or price policies

***

## 6. Feature definitions

Calculate all features **independently per instrument**.

### Log returns

For eligible adjacent observations:

\[
r_t = \log(C_t / C_{t-1})
\]

Do not calculate across an unsupported continuity break.

### Trailing volatility

For a window of \(W\) eligible returns:

\[
\sigma_t =
\sqrt{
\frac{1}{W-1}
\sum_{i=t-W+1}^{t}
(r_i-\bar{r}_t)^2
}
\]

Requirements:

- Exactly `W` returns are needed.
- `ddof=1` is explicit.
- No centered windows.
- No annualization in the MVP.
- No backward filling.
- The feature at bar `t` becomes usable no earlier than the latest availability time of its inputs.

### Efficiency ratio

For `L` price changes:

\[
ER_t =
\frac{
|C_t-C_{t-L}|
}{
\sum_{i=t-L+1}^{t}|C_i-C_{i-1}|
}
\]

Direction is determined from:

\[
D_t=C_t-C_{t-L}
\]

Classification:

```text
ER >= threshold and D > 0 → up
ER >= threshold and D < 0 → down
otherwise                 → non_directional
```

If all price changes are zero:

```text
ER = 0
direction = non_directional
```

`L` price changes require `L + 1` prices.

### Continuity rules

Reset rolling state at unsupported gaps, then rebuild warm-up history.

Do not reset merely because wall-clock time crossed an exchange closure. Continuity must follow the approved calendar and bar-generation policy.

***

## 7. Threshold fitting and causality

### Volatility thresholds

Fit thresholds separately for each instrument using eligible training observations:

```text
q_low  = training volatility quantile at configured low probability
q_high = training volatility quantile at configured high probability
```

Use the specified linear interpolation convention.

Classification:

```text
volatility <= q_low                 → low
q_low < volatility <= q_high        → normal
volatility > q_high                 → high
```

Reject fitting when:

- Too few eligible training observations exist.
- Thresholds are non-finite.
- `q_low >= q_high`.

A flat training series may therefore fail threshold fitting even though its individual price records are structurally valid.

### Required causality rules

1. **Training selection uses availability time:** fitted observations must be available before `fit_end`.
2. **Features are trailing:** a label uses only observations available by that label’s `available_at`.
3. **Thresholds are frozen for the inference interval.**
4. **No test-period quantiles, normalization, or retrospective relabeling.**
5. **No future-looking smoothing.**
6. **No classifier selection based on inference-period P&L.**

Earlier history may support training-feature warm-up, but only observations inside the declared fit interval enter threshold estimation.

### Prefix invariance

With thresholds and configuration fixed:

> Adding future observations must not change previously produced labels or their feature values.

Changing the training interval, configuration, or input snapshot creates a new classification version.

### Execution timing

A label derived from a completed bar must not authorize a trade earlier than its availability. Same-bar closing-price execution requires a separately justified execution model; it is not granted by this specification.

***

## 8. Output contract

### Label table

Publish `regimes.parquet` with one row per requested inference bar.

| Column | Meaning |
|---|---|
| `instrument` | Input instrument |
| `bar_close_at` | Labelled bar’s closing timestamp |
| `available_at` | Earliest permitted use of this label |
| `volatility` | Trailing volatility, nullable during warm-up |
| `efficiency_ratio` | Trailing efficiency ratio, nullable during warm-up |
| `direction` | `up`, `down`, `non_directional`, or `unknown` |
| `volatility_regime` | `low`, `normal`, `high`, or `unknown` |
| `regime_label` | Combined label or `unknown` |
| `is_classified` | Boolean |
| `unknown_reason` | Reason when classification is unavailable |
| `threshold_set_id` | Reference to fitted per-instrument thresholds |

Do not emit a probability or confidence score: this rule-based MVP does not estimate either.

### Threshold artifact

Publish `thresholds.json` containing:

- Instrument
- Fit interval
- Eligible training sample count
- Low/high volatility thresholds
- Quantile convention
- Configuration hash
- Classifier version
- Threshold-set identity
- Upstream lineage

### Diagnostics

Publish `regime-report.json` containing:

- Input and output row counts
- Classified and unknown counts per instrument
- Unknown reasons
- Regime occupancy
- Consecutive-run lengths
- Transition counts
- Warnings and readiness decision
- Lineage and implementation identity

Exclude `unknown` rows from classified transition statistics and do not count transitions across continuity breaks.

Diagnostics may summarize the completed inference interval for reporting, but must never feed back into earlier labels.

### Bundle

```text
regime-bundles/<bundle_id>/
├── regimes.parquet
├── thresholds.json
├── regime-report.json
├── config.json
└── manifest.json
```

The manifest hashes the component files. Do not create circular hash dependencies.

***

## 9. State and graph behavior

### Proposed states

| Status | Meaning |
|---|---|
| `regime_running` | Execution has started |
| `regime_ready` | Output contract passed and bundle is published |
| `regime_blocked` | Preconditions or required coverage are not satisfied |
| `regime_failed` | Computation or publication failed |

Preserve the existing research iteration counter. Regime preparation does not count as a calibration round.

### Success update

Conceptual state addition:

```python
{
    "status": "regime_ready",
    "regime_bundle_ref": "...",
    "regime_manifest_sha256": "...",
    "regime_report_ref": "...",
}
```

These are proposed fields, not verified names in your repository.

### Routing

```text
regime_ready   → Signal Agent, if enabled and authorized
regime_blocked → Stop with diagnostic evidence
regime_failed  → Stop with failure evidence
```

The MVP integration graph ends after the Regime Agent until the Signal Agent exists.

### Publication rules

- Publish only after output validation.
- Never leave stale successful references on failure.
- Never return `regime_ready` for an all-unknown instrument.
- Preserve failed-run diagnostics outside the approved-bundle namespace.
- Reuse cached output only after integrity and compatibility verification.

***

## 10. Proposed package interfaces

Suggested layout:

```text
regime_phase/
├── pyproject.toml
├── configs/
│   └── causal-volatility-efficiency-v1.yaml
├── src/trading_regime/
│   ├── contracts.py
│   ├── features.py
│   ├── fitting.py
│   ├── classification.py
│   ├── validation.py
│   ├── artifacts.py
│   ├── node.py
│   └── __main__.py
└── tests/
```

Proposed interfaces:

```python
verify_regime_input(...)
compute_causal_features(...)
fit_thresholds(...)
classify_regimes(...)
validate_regime_output(...)
publish_regime_bundle(...)
load_verified_regime_bundle(...)
regime_agent(state, ...)
```

Separate pure numerical functions from file access, graph state, and publication.

The node should return state updates rather than mutate its caller’s input.

### Resource requirements

- Configurable maximum rows and memory budget
- Cancellation checks between instruments or chunks
- Bounded diagnostic examples
- No provider-network access in the MVP
- Rolling state retained correctly across processing chunks
- Same results for supported chunked and batch execution

***

## 11. Acceptance tests

| Test | Required outcome |
|---|---|
| Provenance-backed reference input | Valid, published regime bundle |
| Rejected or missing upstream quality evidence | Block before classification |
| Modified input data or report | Integrity failure |
| Unsupported zero/negative close | Explicit compatibility failure |
| Insufficient training samples | Block |
| Equal volatility thresholds | Block |
| Warm-up rows | Preserved as `unknown` with reason |
| Unsupported gap | Rolling state resets |
| Valid exchange closure | No incorrect gap reset |
| Threshold boundary values | Match documented comparison rules |
| Multiple instruments | No rolling-state or threshold contamination |
| Future data appended | Earlier labels remain unchanged |
| Future prices changed | Earlier labels remain unchanged |
| Inference distribution changed | Fitted thresholds remain unchanged |
| Input/configuration changed | Old approval not silently reused |
| Chunked versus batch processing | Equivalent supported results |
| Publication interruption | No approved partial bundle |
| Blocked/failed run | Downstream spy is never invoked |
| Repeated execution | Verified reuse or reproducible output |

Use your existing real-data fixture for integration tests. Small explicitly labelled mathematical unit-test sequences may exercise boundary behavior, but they must not be presented as market evidence.

No accuracy, profitability, or robustness claim is established merely by passing these tests.

***

## 12. UI and artifact updates

### Research Control Center

Add a **Classify regimes** operation with:

1. Approved data-bundle selection.
2. Regime configuration selection.
3. Explicit fit and inference intervals.
4. Required regression gates.
5. Authorization check.
6. Execution and verified publication.

Display separately:

```text
Regression gate
Upstream data quality
Input/output integrity
Classification readiness
Research acceptance: Not evaluated
```

Add a **Regimes** panel showing configuration, threshold-fit interval, occupancy, unknown coverage, transitions, and artifact downloads.

Do not silently reuse the same fit period for all walk-forward folds.

### Documentation changes

| Artifact | Required update |
|---|---|
| Architecture | Data → quality gate → Regime → Signal dependency |
| Data Phase | Availability, continuity, warm-up, and approved-reader obligations |
| Regime specification | This document and subsequent implementation decisions |
| Artifact contracts | Regime schemas, hashes, lineage, compatibility |
| Testing guide | Causality, isolation, corruption, and routing tests |
| UI specification | Classification controls and independent evidence indicators |
| CI workflow | Existing phase regressions plus Regime tests |

## 13. Implementation milestones

1. **Contracts:** agree upstream mapping, availability semantics, configuration, and output schemas.
2. **Pure features:** implement trailing volatility and efficiency ratio.
3. **Fitting:** add per-instrument training-only thresholds.
4. **Classification:** implement labels, warm-up, and continuity handling.
5. **Evidence:** add diagnostics, manifest, publication, and verified reader.
6. **Graph integration:** connect only after the approved Data Agent gate.
7. **UI and CI:** expose classification after regression and authorization checks.

**Definition of done:** a quality-approved dataset produces integrity-verifiable, causally valid regime labels; failed prerequisites block downstream execution; prefix-invariance and train/inference-isolation tests pass; documentation and UI accurately distinguish classification readiness from strategy acceptance.
**The Fan-in Barrier is a deterministic readiness gate that releases the Signal Agent only when all required upstream artifacts are complete, verified, and mutually compatible.** It must check more than “both nodes finished”: it must prevent mismatched datasets, stale results, invalid regime alignment, and unauthorized execution.

**Specification:** `fan-in-barrier-v0.1.0`  
**Status:** Proposed design—not implemented, repository-verified, or packaged for download.

## Purpose

The barrier answers:

> “Do the approved market data and regime classifications belong to this exact research execution, and can the Signal Agent safely consume them together?”

### Responsibilities

- Require all declared upstream inputs.
- Verify artifact integrity and approval evidence.
- Match request, data, configuration, and execution identities.
- Validate data–regime alignment and causal availability.
- Publish a readiness report and downstream input manifest.
- Block downstream execution on incompatible or incomplete inputs.

### Exclusions

The barrier must not:

- Repair data or regenerate classifications.
- Refit regime thresholds.
- Select a better-performing regime.
- Override data-quality rejection.
- Grant execution permissions.
- Treat successful synchronization as research acceptance.

## Architecture placement

**Your current Data → Regime dependency is sequential.** The Regime Agent consumes the approved Data Agent output, so those two agents must not be launched independently in parallel.

### Current pipeline

```text
Strategy Supervisor
         │
         ▼
Data Agent + Quality Gate
         │
         ▼
Approved Data Bundle
         │
         ▼
Regime Agent
         │
         ▼
Fan-in Readiness Gate
  verifies Data + Regime artifacts
         │
    ┌────┴─────┐
    │          │
  READY      BLOCKED
    │          │
    ▼          ▼
Signal Agent  Stop + evidence
```

Here, “fan-in” means **combining artifact dependencies**, not waiting for parallel tasks. A multi-source scheduling edge is unnecessary for this topology.

### Future parallel topology

Only introduce scheduling fan-in when genuinely independent branches exist:

```text
             Approved Data Bundle
                       │
              ┌────────┴─────────┐
              ▼                  ▼
      Signal-input view      Regime Agent
      preparation branch
              │                  │
              └────────┬─────────┘
                       ▼
                Fan-in Barrier
                       │
                       ▼
                 Signal Agent
```

The signal-input preparation branch is optional future work—not a new requirement for your MVP.

## Synchronization versus validation

These are separate responsibilities:

| Layer | Responsibility |
|---|---|
| Graph scheduler | Wait for declared upstream nodes to complete |
| Fan-in Barrier | Verify their outputs are acceptable together |
| Signal Agent reader | Verify the released input manifest before consumption |

For a static parallel topology, LangGraph supports a multi-source edge that waits for all listed source nodes before executing the destination; separate ordinary edges are not a substitute for declaring that join explicitly. See the [LangGraph graph reference](https://reference.langchain.com/python/langgraph/graphs/).

Illustrative construction:

```python
# Illustrative only: these future branch nodes are not yet implemented.
builder.add_edge(
    ["prepare_signal_inputs", "regime_agent"],
    "fan_in_barrier",
)
```

**A scheduling join does not validate hashes, quality decisions, lineage, or temporal alignment.** Those checks belong inside the barrier.

## Execution identity

Every input receipt must be associated with a frozen execution context.

| Field | Purpose |
|---|---|
| `run_id` | Research execution identity |
| `generation_id` | Identifies a particular planned input generation |
| `request_sha256` | Accepted normalized request |
| `execution_plan_sha256` | Frozen supervisor plan |
| `fold_id` | Walk-forward fold, or an explicit single-fold identifier |
| `barrier_contract_version` | Barrier interpretation rules |

### Generation rules

- A technical retry retains the same generation.
- Changing the request, approved dataset, regime configuration, fit interval, or required input set creates a new generation.
- Receipts from different generations cannot be combined.
- The barrier does not increment the calibration iteration counter.
- Reused cached artifacts require a new receipt binding them to the current execution after verification.

**Do not equate artifact reuse with accepting an old run’s receipt.**

## Input contracts

Use small receipts in graph state; keep datasets outside checkpoint state.

### Data receipt

Required conceptual fields:

```text
execution context
producer contract version
approved data manifest reference + hash
data quality report reference + hash
snapshot identity
bar specification identity
declared instrument coverage
declared time coverage
```

The barrier must verify that:

- The Data Quality decision is `accept`.
- All required quality checks completed.
- Referenced files match their recorded hashes.
- The approved data contract is supported.
- The dataset satisfies the current request.

### Regime receipt

Required conceptual fields:

```text
execution context
producer contract version
regime manifest reference + hash
regime report reference + hash
consumed data manifest hash
regime configuration hash
threshold artifact reference + hash
fit and inference intervals
declared instrument coverage
```

The decisive relationship is:

```text
regime.consumed_data_manifest_sha256
    ==
data.approved_data_manifest_sha256
```

Matching snapshot names or filenames is insufficient.

### Trust boundary

Receipt fields are claims until verified against the referenced manifests and files.

Hash verification establishes consistency with a trusted reference; it does not independently establish that the dataset is economically correct or that its producer is trustworthy.

## Required checks

Assign stable identifiers to checks so reports and tests remain comparable.

| Check ID | Requirement |
|---|---|
| `FAN-001` | All declared receipts exist |
| `FAN-002` | Run, generation, request, plan, and fold identities match |
| `FAN-003` | Receipt and manifest schema versions are supported |
| `FAN-004` | Referenced artifacts exist and pass integrity verification |
| `FAN-005` | Upstream approval and readiness requirements are satisfied |
| `FAN-006` | Regime output references the exact approved data bundle |
| `FAN-007` | Instruments and bar specifications are compatible |
| `FAN-008` | Required time coverage and row alignment are valid |
| `FAN-009` | Availability and fit/inference boundaries satisfy causality rules |
| `FAN-010` | Unknown-regime treatment matches the frozen policy |
| `FAN-011` | Execution authorization permits the requested next stage |
| `FAN-012` | Readiness evidence is published before release |

Checks must not silently become optional when metadata is missing.

## Alignment and causality

### Row alignment

For the MVP, use exact alignment on the declared canonical bar key:

```text
(instrument, bar_close_at)
```

Requirements:

- Keys are unique in both inputs.
- Every requested inference bar has exactly one regime row.
- Historical warm-up data outside the inference interval is not mistaken for missing classifications.
- No nearest-time matching, implicit resampling, forward filling, or silent inner-join row loss.
- Unsupported multi-timeframe joins block execution.

This does not require the complete Data and Regime tables to have identical row counts: the Data bundle may include additional training and warm-up history.

### Availability

The downstream input must expose a conservative availability timestamp:

```text
signal_input_available_at =
    latest required data availability,
    regime availability,
    fitted-threshold effective availability
```

The contract must distinguish:

- **Historical availability:** when information could have been used under the declared research model.
- **Artifact creation time:** when this batch computation actually ran.

Do not use wall-clock file creation time as a substitute for historical information availability.

### Fit boundaries

Verify that:

- The regime fit interval matches the intended fold.
- Fitting observations were available before its declared cutoff.
- Inference begins no earlier than the permitted fitted-model effective time.
- Output does not reference another fold’s thresholds.

The barrier verifies recorded constraints; it does not replace the Regime Agent’s causality and prefix-invariance tests.

### Unknown classifications

Freeze one of these policies in the execution plan:

| Policy | Behavior |
|---|---|
| `block` | Required inference rows must all be classified |
| `mask` | Preserve unknown rows and mark them ineligible for signal generation |

For the MVP, permit masking only for documented warm-up or gap-reset reasons. Unexpected unknown reasons block release.

Never convert `unknown` into `non_directional`.

## State ownership

Use explicit input slots rather than shared global updates:

```python
{
    "data_receipt": ...,
    "regime_receipt": ...,
    "barrier_result": ...,
}
```

### Ownership rules

- Data producers own `data_receipt`.
- Regime producers own `regime_receipt`.
- The barrier owns `barrier_result`.
- Parallel branches do not both write a scalar `status`.
- Append-only event aggregation must handle replay without silently accepting conflicting receipts.

LangGraph uses reducers to control how concurrent state updates are combined; state ownership and reducer behavior must therefore be deliberate. See the [LangGraph Graph API documentation](https://docs.langchain.com/oss/python/langgraph/graph-api).

For the static MVP, separate receipt fields are preferable to a complex general-purpose receipt reducer.

## Decisions and routing

| Decision | Meaning | Signal execution |
|---|---|---|
| `ready` | Required compatibility and publication checks passed | Permitted only within existing authorization |
| `blocked` | Inputs violate a declared prerequisite or policy | Prohibited |
| `failed` | Verification or publication could not complete reliably | Prohibited |

Examples:

```text
Missing receipt at barrier evaluation → blocked
Mismatched data lineage              → blocked
Quality decision requires review     → blocked
Hash mismatch                        → blocked
Storage read error                   → failed
Readiness publication error          → failed
```

“Waiting” is an orchestration/UI state—not a successful barrier decision.

### Upstream failure

If an upstream node raises an unhandled exception, the graph may stop before the barrier executes. The worker must record that failure; the barrier cannot promise a report for an invocation it never receives.

If producers intentionally return structured failure receipts, the graph may route them to a diagnostic evaluation, but never to the Signal Agent.

### Release invariant

```text
Signal Agent may execute only when:

barrier decision == ready
AND readiness manifest is verified
AND generation matches the active execution
AND execution authorization remains valid
```

The barrier cannot upgrade the supervisor’s `plan_only` authorization.

## Evidence artifacts

Proposed approved output:

```text
fan-in-bundles/<bundle_id>/
├── readiness-report.json
├── input-manifest.json
└── manifest.json
```

### Readiness report

Include:

- Schema and barrier implementation versions
- Execution context
- Decision
- Per-check outcomes and reason codes
- Verified input hashes
- Instrument and inference coverage
- Unknown-row counts and policy
- Authorization reference
- Bounded mismatch examples
- Creation timestamp

### Input manifest

This is the Signal Agent’s input contract:

- Exact Data and Regime manifest references and hashes
- Execution and fold identity
- Required instruments and inference interval
- Join key and alignment policy
- Unknown-handling policy
- Availability contract
- Barrier configuration hash

The barrier should publish references rather than duplicate large datasets. Any derived mask file must be included and hashed explicitly.

The outer manifest hashes the report and input manifest. Avoid circular hash dependencies.

Blocked and failed diagnostics belong outside the approved namespace.

## Reliability requirements

### Idempotency

Compute the logical release identity from:

```text
execution context
+ verified upstream manifest hashes
+ barrier configuration
+ barrier implementation version
```

A repeat evaluation may reuse an existing bundle only after verifying its contents.

### Retry behavior

- Retry bounded transient storage failures.
- Do not retry deterministic compatibility failures without changed inputs.
- Revalidate artifact identities after retry or resume.
- Do not claim exactly-once node execution.
- Ensure repeated execution cannot produce conflicting logical releases.

LangGraph durability does not automatically make external artifact writes transactional; replay-safe publication remains an application responsibility. See [durable execution guidance](https://docs.langchain.com/oss/python/langgraph/durable-execution).

### Cancellation and deadlines

- The worker enforces execution deadlines.
- Do not implement a sleeping/polling loop inside the barrier.
- Check cancellation before publication and release.
- Record cancellation durably.
- Cancellation after publication must still prevent subsequent execution.
- A UI button must not claim cancellation completed before worker acknowledgement.

Dynamic fan-out, distributed receipt collection, quorum joins, and partial release are outside the MVP.

## Acceptance tests

| Test | Expected outcome |
|---|---|
| Compatible approved inputs | One valid logical release |
| Parallel branches finish in either order | Same compatibility decision |
| Required receipt missing | Block |
| Wrong run or generation | Block |
| Wrong walk-forward fold | Block |
| Regime references another data bundle | Block |
| Modified file or manifest | Block |
| Unsupported schema | Block |
| Missing quality approval | Block |
| Duplicate canonical keys | Block |
| Missing required inference rows | Block |
| Extra warm-up data outside inference | Allowed under declared scope |
| Unknown rows under `block` policy | Block |
| Allowed unknown rows under `mask` policy | Preserve rows and eligibility mask |
| Incorrect availability/fit boundary | Block |
| Existing `plan_only` authorization | No Signal execution |
| Upstream exception | No Signal execution; worker records failure |
| Publication interrupted | No consumable partial release |
| Checkpoint replay | No conflicting duplicate release |
| Cancellation before downstream execution | No Signal execution |

Add a downstream spy/mock to every blocking-path test. Checking only the returned status is insufficient.

## Proposed implementation structure

```text
fanin_phase/
├── pyproject.toml
├── src/trading_fanin/
│   ├── contracts.py
│   ├── verification.py
│   ├── alignment.py
│   ├── policy.py
│   ├── artifacts.py
│   └── node.py
└── tests/
    ├── test_contracts.py
    ├── test_lineage.py
    ├── test_alignment.py
    ├── test_authorization.py
    ├── test_publication.py
    └── test_graph_routing.py
```

Proposed interfaces—not existing repository APIs:

```python
verify_upstream_receipts(...)
validate_input_compatibility(...)
evaluate_readiness(...)
publish_readiness_bundle(...)
load_verified_signal_inputs(...)
fan_in_barrier(state, ...)
```

## Documentation and UI updates

| Artifact | Required update |
|---|---|
| Architecture | Distinguish sequential readiness gating from parallel scheduling fan-in |
| Data Phase | Declare approved-manifest, availability, and continuity obligations |
| Regime specification | Bind output to exact consumed data and fold |
| Signal specification | Require the verified barrier input manifest |
| Supervisor plan | Freeze required inputs, generation, alignment, and unknown policy |
| UI | Show branch progress, barrier decision, and blocking reasons separately |
| CI | Test compatibility failures, replay, authorization, and downstream blocking |

Suggested UI presentation:

```text
Upstream inputs
Data bundle          Verified
Regime bundle        Verified

Compatibility
Execution identity   Match
Data lineage         Match
Inference alignment  Accepted
Temporal availability Accepted

Barrier decision     READY
Next-stage authority NOT GRANTED
Research acceptance  NOT EVALUATED
```

**Definition of done:** the Signal Agent cannot start from merely completed nodes or a manually set status; it requires a verified, generation-bound readiness manifest covering compatible Data and Regime artifacts, with authorization and failure-path tests enforced.
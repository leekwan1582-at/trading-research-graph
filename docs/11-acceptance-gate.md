# Acceptance Gate Specification

**The Acceptance Gate is the final research-decision controller: it evaluates whether a completed research run satisfies the predeclared acceptance policy and determines whether the run is accepted, rejected, or requires review.** It must never generate new data, refit models, rerun calibration, or reinterpret outcomes with ad hoc rules.

**Specification:** `acceptance-gate-v0.1.0`  
**Status:** Proposed specification only. It is not yet implemented, repository-verified, or packaged for download.

## 1. Purpose

The Acceptance Gate answers:

> “Given the verified outputs of the completed research pipeline, does this strategy instance satisfy the predefined acceptance criteria for this run?”

It is the **last decision node** before the Reporting Agent or final research disposition.

### Included

- Verify completed upstream artifacts
- Evaluate explicit acceptance policy
- Apply pass/fail/review rules
- Publish a decision bundle
- Freeze the decision with lineage and evidence
- Prevent post hoc reinterpretation

### Excluded

- Data cleaning
- Regime classification
- Signal generation
- Parameter search
- Backtest execution
- Diagnostics computation
- Manual exception approval inside the automated gate
- Live deployment authorization

**Acceptance means the run passed the declared research policy. It does not mean the strategy is safe for production trading.**

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
        │
        ▼
 Acceptance Gate
┌─────────────────────────────────────┐
│ Verify all final upstream artifacts │
│ Load frozen acceptance policy       │
│ Evaluate mandatory requirements     │
│ Apply acceptance decision rules     │
│ Publish acceptance bundle           │
└──────────────────┬──────────────────┘
                   │
         acceptance_ready
                   │
                   ▼
            Reporting Agent
```

The Acceptance Gate must only run after diagnostics are complete and verified.

## 3. Core principle

The gate must operate on a **frozen policy** defined before seeing the final held-out results.

That policy may include:

- minimum trade count
- maximum drawdown
- minimum net return
- minimum expectancy
- minimum profit factor
- maximum instability across folds
- required artifact completeness
- required integrity checks
- review triggers

It must **not** invent new rules after outcomes are observed.

## 4. Decision types

Use exactly three business outcomes:

| Decision | Meaning |
|---|---|
| `accept` | All mandatory requirements passed |
| `reject` | One or more mandatory rejection conditions were triggered |
| `review` | Automation cannot approve; explicit human review is required |

Keep system failures separate from business decisions.

| Status | Meaning |
|---|---|
| `acceptance_ready` | Decision bundle published successfully |
| `acceptance_blocked` | Missing or incompatible prerequisites |
| `acceptance_failed` | Gate execution or publication failed |

A failed gate is not a rejection. It is an incomplete research decision.

## 5. Inputs

The Acceptance Gate consumes **verified, frozen upstream outputs**.

### Required inputs

| Input | Requirement |
|---|---|
| Approved data lineage | Verified and complete |
| Regime bundle, if used | Verified and compatible |
| Signal bundle | Verified and compatible |
| Calibration bundle | Verified and accepted for backtest use |
| Backtest bundle | Verified and complete |
| Diagnostics bundle | Verified and complete |
| Acceptance policy | Frozen version with content hash |
| Execution context | Matching request, run, generation, fold set, and plan |

### Identity invariants

At minimum, the gate must verify consistent lineage across:

- `request_sha256`
- `execution_plan_sha256`
- `run_id`
- `generation_id`
- `strategy_id`
- `signal_variant_id`
- `calibration_bundle_ref`
- `backtest_bundle_ref`
- `diagnostics_bundle_ref`
- `acceptance_policy_sha256`

If diagnostics were produced from a different backtest bundle, the gate must block.

## 6. Acceptance policy contract

The policy must be machine-readable and versioned.

Illustrative structure:

```yaml
schema_version: "1.0"
policy_id: "research-acceptance-v1"

required_artifacts:
  diagnostics: true
  backtest: true
  calibration: true

hard_reject:
  maximum_drawdown: 0.20
  minimum_closed_trades: 30
  minimum_net_return: 0.00

required_pass:
  minimum_profit_factor: 1.10
  minimum_expectancy_per_trade: 0.0

review_rules:
  unstable_fold_dispersion: 0.35
  high_concentration_warning: true
  low_trade_count_warning_below: 50

integrity:
  require_all_hash_checks: true
  require_supported_schema_versions: true
```

**The threshold values above are only examples.** They are not recommended defaults.

### Policy rules

- Unknown keys must be rejected.
- Unsupported schema versions must block execution.
- Every metric referenced by policy must be explicitly defined in upstream contracts.
- Metric definitions must match the diagnostics contract exactly.
- Optional rules must still be versioned and documented.

A policy cannot depend on free-text interpretation.

## 7. Evaluation domains

The gate should evaluate four domains separately.

| Domain | Purpose |
|---|---|
| Integrity | Are all artifacts authentic, complete, and lineage-consistent? |
| Completeness | Were all required pipeline stages successfully completed? |
| Quantitative acceptance | Did the run satisfy numerical pass/reject criteria? |
| Review triggers | Is the result acceptable only with explicit human review? |

### Integrity

Block or fail if:

- hashes do not match
- manifests are missing
- schema versions unsupported
- lineage inconsistent
- required artifacts missing

### Completeness

Block if:

- diagnostics incomplete
- backtest incomplete
- calibration not ready
- expected folds missing
- mandatory metrics absent

### Quantitative acceptance

Typical metrics may include:

- net return
- maximum drawdown
- expectancy
- closed trade count
- win rate
- profit factor
- average holding period
- exposure
- fold-level stability

These are examples. The gate only uses what the frozen policy explicitly declares.

### Review triggers

Examples:

- acceptable performance but low trade count
- acceptable return but high fold dispersion
- acceptable headline metrics with concentrated outcome dependence
- valid run with unusual metric combinations requiring signoff

A review outcome must preserve the exact reasons.

## 8. Metric source of truth

The Acceptance Gate must not recompute performance metrics from raw trades unless that recomputation is explicitly part of the diagnostics contract.

For MVP:

- Diagnostics Agent is the source of acceptance metrics.
- Acceptance Gate verifies diagnostics integrity and reads published metrics.
- The gate may perform consistency checks, but not an alternate shadow analytics system.

If a consistency check is required, it must be narrowly defined and versioned.

## 9. Fold and scope handling

Acceptance must declare exactly what scope it applies to.

### Allowed scopes

| Scope | Meaning |
|---|---|
| `single_fold` | One defined research fold |
| `multi_fold` | A fixed set of folds declared in the plan |
| `aggregate_run` | An aggregate across declared folds |

The gate must never silently aggregate over an incomplete or mixed fold set.

### Multi-fold rules

If acceptance is based on multiple folds, the policy must define:

- required fold identities
- whether all folds are mandatory
- whether aggregation is equal-weighted or capital-weighted
- how missing folds are handled
- how dispersion or instability is measured

A partial fold set must not be treated as complete.

## 10. Review versus reject

This distinction matters.

### Reject

Use when a declared hard rule fails.

Examples:

- drawdown exceeds hard maximum
- closed trades below hard minimum
- net return below minimum requirement
- required integrity check fails

### Review

Use when the automated system cannot safely approve but policy does not require outright rejection.

Examples:

- fold dispersion above review threshold
- concentration warning triggered
- minimum warning trade count breached but hard minimum still passed

### Important rule

A review outcome is **not** an acceptance with yellow color. It is a separate decision class that blocks automatic promotion.

## 11. Evidence bundle

### Required bundle

```text
acceptance-bundles/<bundle_id>/
├── acceptance-decision.json
├── acceptance-report.json
├── acceptance-policy.json
└── manifest.json
```

### `acceptance-decision.json`

Minimum fields:

| Field | Meaning |
|---|---|
| `decision` | `accept`, `reject`, or `review` |
| `decision_time` | Publication timestamp |
| `policy_id` | Applied policy |
| `policy_sha256` | Exact policy identity |
| `run_id` | Research run identity |
| `generation_id` | Generation identity |
| `scope_id` | Fold set or run scope |
| `accepted_for` | Research interpretation only |
| `reason_codes` | Structured reasons |
| `upstream_refs` | Backtest/diagnostics/calibration references |

### `acceptance-report.json`

Should include:

- all evaluated rules
- pass/fail/review status per rule
- referenced metrics and their values
- artifact completeness and integrity results
- fold coverage summary
- bounded warning examples
- explicit statement that acceptance is not production approval

### `manifest.json`

Must hash:

- decision file
- report file
- policy file

It must also reference upstream verified artifact manifests.

## 12. Rule evaluation model

Evaluate rules in deterministic order.

### Recommended order

1. integrity checks
2. completeness checks
3. hard rejection checks
4. required pass checks
5. review checks
6. final decision composition
7. publication

### Composition logic

Illustrative deterministic rule:

```text
If any integrity/completeness blocker → blocked or failed
Else if any hard reject rule fails    → reject
Else if any required pass rule fails  → reject
Else if any review rule triggers      → review
Else                                  → accept
```

This precedence must be explicit and versioned.

## 13. State transitions

Suggested statuses:

| Status | Meaning |
|---|---|
| `acceptance_running` | Decision evaluation started |
| `acceptance_ready` | Decision bundle published |
| `acceptance_blocked` | Missing or incompatible prerequisites |
| `acceptance_failed` | Gate execution failed |

Conceptual state update:

```python
{
    "status": "acceptance_ready",
    "acceptance_bundle_ref": "...",
    "acceptance_manifest_sha256": "...",
    "acceptance_decision": "accept",
}
```

Field names are proposed only.

### Routing invariant

```text
Reporting Agent may run only if:
    acceptance_ready
    AND acceptance bundle verifies
```

If the reporting system distinguishes accepted versus rejected reports, that routing must be explicit.

## 14. Reliability requirements

- deterministic rule ordering
- no hidden fallback logic
- no dynamic thresholds derived from observed results
- no partial publication of accepted decisions
- idempotent bundle publication
- integrity verification before cache reuse
- explicit failure if metrics are missing
- no silent coercion of null/NaN values into zeros
- bounded report size and reason examples

If the same verified inputs and same policy are re-evaluated, the decision must be identical.

## 15. Failure conditions

The gate must block or fail on:

- missing diagnostics bundle
- missing required metric referenced by policy
- unsupported policy version
- hash mismatch in any required upstream artifact
- fold-set mismatch
- mixed generation identities
- corrupted acceptance policy file
- incomplete publication of decision artifacts

### Business rejection is not system failure

A strategy can be **rejected successfully**.

That means:

- the gate ran correctly,
- the policy was applied correctly,
- and the resulting decision is `reject`.

This is a valid and important outcome.

## 16. Acceptance tests

Minimum required tests:

| Test | Expected outcome |
|---|---|
| Clean reference run meeting all criteria | `accept` |
| Hard drawdown breach | `reject` |
| Trade count below hard minimum | `reject` |
| Good metrics but review warning triggered | `review` |
| Missing diagnostics bundle | `blocked` |
| Diagnostics from wrong backtest bundle | `blocked` |
| Hash mismatch in required artifact | `blocked` |
| Unsupported policy schema | `blocked` |
| Missing metric referenced by policy | `blocked` or `failed` per contract |
| Same inputs re-evaluated | identical decision |
| Partial fold set when all folds required | `blocked` |
| Interrupted publication | no consumable acceptance bundle |
| Any blocked/failed path | Reporting spy never invoked |

For multi-fold acceptance later, add tests for aggregation and dispersion logic separately.

## 17. Proposed package structure

```text
acceptance_phase/
├── pyproject.toml
├── policies/
│   └── research-acceptance-v1.yaml
├── src/trading_acceptance/
│   ├── contracts.py
│   ├── inputs.py
│   ├── policy.py
│   ├── rules.py
│   ├── evaluation.py
│   ├── artifacts.py
│   ├── validation.py
│   ├── node.py
│   └── __main__.py
└── tests/
```

Suggested interfaces:

```python
load_verified_acceptance_inputs(...)
validate_acceptance_policy(...)
evaluate_acceptance_rules(...)
compose_acceptance_decision(...)
publish_acceptance_bundle(...)
load_verified_acceptance_bundle(...)
acceptance_gate(state, ...)
```

## 18. UI and documentation updates

### Research Control Center

Add an **Acceptance Gate** view showing:

- applied policy ID and hash
- upstream bundle lineage
- rule-by-rule results
- final decision
- downloadable decision/report artifacts

Display these independently:

```text
Artifact integrity
Research completeness
Acceptance decision
Production approval: Not evaluated
```

### Documentation updates required

| Artifact | Required update |
|---|---|
| Architecture | Add final gate before reporting |
| Diagnostics spec | Declare metric contract used by acceptance |
| Backtest spec | Clarify that diagnostics, not backtest alone, feed the gate |
| Research policy docs | Define allowable acceptance policies |
| Artifact contracts | Define acceptance decision/report schemas |
| CI workflow | Add acceptance rule and lineage tests |
| UI spec | Add final-decision display and evidence browsing |

## 19. Implementation milestones

1. Finalize diagnostics metric contract.
2. Define machine-readable acceptance policy schema.
3. Implement verified input loading and lineage checks.
4. Implement deterministic rule engine.
5. Implement decision/report publication.
6. Add acceptance/rejection/review test cases.
7. Integrate routing to reporting.

**Definition of done:** the Acceptance Gate consumes verified final research artifacts, applies a frozen and machine-readable acceptance policy deterministically, publishes an immutable decision bundle, and cleanly distinguishes accepted, rejected, review-required, blocked, and failed outcomes without modifying any upstream result.
**Add a “Phase 3.1 — Data Quality Gate” inside the Data Agent, before it publishes `data_ready`.** Update the architecture, Data Phase guide, artifact contracts, tests, and UI together so downstream agents cannot bypass the gate.

Below is a repository-ready implementation plan. **These are proposed changes—not edits already applied to your repository.** The exact integration points must be checked against your existing `trading_data` implementation.

## Updated architecture

Keep the Data Agent as the external graph node. Put the quality checks inside its preparation workflow rather than creating another independently controlled agent.

```text
Validated Research Request
           │
           ▼
Strategy Supervisor
           │
           ▼
Data Agent
┌────────────────────────────────────────────┐
│ Resolve approved snapshot                  │
│                │                           │
│ Verify source identity and integrity       │
│                │                           │
│ Load candidate data                        │
│                │                           │
│ Validate schema and market semantics       │
│                │                           │
│ Check coverage against declared policy     │
│                │                           │
│ Evaluate quality decision                  │
│       ┌────────┼──────────────┐             │
│       ▼        ▼              ▼             │
│     REJECT   REVIEW         ACCEPT          │
│       │        │              │             │
│ Save report / quarantine     Publish        │
│ Stop downstream execution    approved       │
│                              bundle        │
└──────────────────────────────┬─────────────┘
                               │
                        status=data_ready
                               │
                               ▼
                   Verified artifact reader
                               │
                               ▼
                   Regime / Signal agents
```

**Important:** your existing supervisor’s `plan_only` and execution-authorization safeguards remain unchanged. Quality acceptance does not grant permission to execute an otherwise unauthorized stage.

## Artifacts to update

Use these as suggested paths; if equivalent documents already exist, update those instead of creating competing versions.

| Artifact | Proposed change |
|---|---|
| `docs/architecture.md` | Add quality gate, failure routes, trust boundaries, and downstream-reader requirements |
| `docs/data-phase.md` | Document preparation, validation, publication, and rejection procedures |
| `docs/data-quality-contract.md` | Define policies, reports, decisions, hashes, and compatibility rules |
| `docs/testing-data-quality.md` | Add positive, negative, tampering, and graph-routing acceptance tests |
| Existing UI specification | Add separate test, quality, integrity, and execution indicators |
| `data_phase/` implementation | Integrate quality evaluation before approved publication |
| `.github/workflows/data-agent.yml` | Add quality-specific evidence and regression coverage |

***

## Step 1 — Preserve the baseline

From your repository root:

```bash
cd ~/trading-research-graph

git status --short
git switch -c feat/data-quality-gate
```

If you have uncommitted changes, review them before proceeding; do not reset or overwrite them.

Activate your existing Data Phase environment:

```bash
source data_phase/.venv/bin/activate

python -m pip check
```

Run the current regression suites:

```bash
python -m pytest request_phase/tests -v
python -m pytest supervisor_phase/tests -v
python -m pytest data_phase/tests -v
```

**Checkpoint:** record the baseline outcome before changing validation behavior.

## Step 2 — Audit existing checks

Do not implement a second OHLCV validator until you identify what already exists.

Locate the package files:

```bash
find data_phase \
  -type d \( -name .venv -o -name __pycache__ \) -prune -o \
  -type f -name '*.py' -print
```

Search for existing validation and publication logic:

```bash
grep -RIn \
  --include='*.py' \
  --exclude-dir=.venv \
  --exclude-dir=__pycache__ \
  -E 'data_ready|validate|duplicate|isfinite|sha256|manifest|publish' \
  data_phase
```

Create a coverage inventory:

| Requirement | Existing function/test | Action |
|---|---|---|
| Required columns and types | Record actual location | Reuse or extend |
| Duplicate bars | Record actual location | Reuse or extend |
| OHLC consistency | Record actual location | Reuse or extend |
| Timestamp handling | Record actual location | Review assumptions |
| Calendar-aware coverage | Record actual location | Add if absent |
| Quality report | Record actual location | Standardize |
| Publication gate | Record actual location | Enforce |
| Downstream verification | Record actual location | Extend |

**Checkpoint:** know which checks are already implemented, which are missing, and which produce no persistent evidence.

## Step 3 — Define quality policies

Create versioned policies before adding thresholds to code.

Suggested structure:

```text
data_phase/
├── policies/
│   ├── crypto-timebars-v1.json
│   └── futures-timebars-v1.json
├── src/
│   └── trading_data/
│       └── quality/
│           ├── contracts.py
│           ├── checks.py
│           └── evaluate.py
└── tests/
    ├── test_quality_checks.py
    ├── test_quality_gate.py
    └── test_quality_artifacts.py
```

Adapt `src/` to your actual package layout.

### Required policy settings

| Area | Explicit policy |
|---|---|
| Bar definition | Instrument identity, frequency, open/close timestamp convention |
| Time handling | Source timezone, canonical timezone, request interval semantics |
| Calendar | Continuous market or named exchange calendar |
| Missing bars | Whether empty intervals should produce bars; permitted gaps |
| Numeric rules | Finite values, volume semantics, instrument-specific price constraints |
| Coverage | Required instruments, requested interval, warm-up history |
| Anomalies | Detection method, thresholds, and severity |
| Warnings | Which warnings may proceed automatically |
| Required checks | Checks that must complete before acceptance |

Avoid universal assumptions:

- Do not impose positive prices on every futures dataset.
- Do not count exchange closures as missing bars.
- Do not assume every provider emits a bar when no trade occurs.
- Do not apply the same outlier thresholds to ES and BTC.
- Do not assume a continuous futures series represents directly executable contract prices.

**Checkpoint:** thresholds and exceptions are configuration, not hidden constants.

## Step 4 — Define decisions and state

Separate **quality decisions** from **pipeline execution status**.

### Quality decisions

| Decision | Meaning | Downstream allowed? |
|---|---|---|
| `accept` | Required checks completed and policy permits the findings | Yes, subject to existing execution authorization |
| `review` | Findings require a recorded policy/review decision | No |
| `reject` | Blocking violations found | No |

Use a separate check result such as `error` when validation itself fails. A validator crash must never become an acceptance.

### Pipeline mapping

| Outcome | Proposed pipeline status |
|---|---|
| Approved bundle published successfully | `data_ready` |
| Review required | `data_review_required` |
| Quality rejected | `data_rejected` |
| Loading, validation, or publication error | `data_failed` |

Add these statuses to your actual state contract and graph routing only after checking compatibility.

**Required invariant:**

```text
data_ready
    requires:
        quality decision = accept
        all required checks completed
        approved bundle published
        artifact references present
        execution authorization satisfied
```

**Checkpoint:** missing reports, missing checks, or missing policies fail closed.

## Step 5 — Implement the check groups

Organize the evaluator into the following groups.

| Group | Checks |
|---|---|
| Structure | Required columns, supported types, nonempty dataset |
| Identity | Snapshot, instruments, bar specification, request compatibility |
| Time | Parseable timestamps, explicit timezone, ordering, duplicate keys |
| Numeric | Nulls, NaN/infinity, volume rules, instrument-specific constraints |
| Market semantics | OHLC relationships and declared adjustment conventions |
| Coverage | Expected bars, missing intervals, boundaries, warm-up |
| Anomalies | Price discontinuities, stale prices, unusual volume |
| Provenance | Source references, input hashes, policy and validator versions |

For OHLC consistency, validate these relationships:

```text
low <= open <= high
low <= close <= high
low <= high
```

Check input ordering **before** any approved sorting step; otherwise sorting could conceal a source-quality issue.

For missing-bar checks, first establish the correct calendar and provider behavior. If a required calendar cannot be resolved, report that check as incomplete—not as “zero gaps.”

### Do not clean silently

The initial quality gate should be observational:

```text
Read → inspect → report → decide
```

Not:

```text
Read → silently fill/drop/repair → report success
```

If cleaning is later introduced, publish a separate transformed dataset with its own lineage and repeat the checks.

**Checkpoint:** validation leaves the original snapshot unchanged.

## Step 6 — Publish quality evidence

Every evaluation should produce a report—even when the dataset is rejected.

### Quality report contract

Document these fields in `docs/data-quality-contract.md`:

| Field | Purpose |
|---|---|
| `schema_version` | Report compatibility |
| `evaluation_id` | Identifies this evaluation |
| `request_sha256` | Binds the evaluation to the accepted request |
| `input_manifest_sha256` | Binds it to the source snapshot manifest |
| `candidate_data_sha256` | Identifies the exact data representation evaluated |
| `policy_id`, `policy_sha256` | Identifies the applied rules |
| `validator_version` | Identifies validation behavior |
| `decision` | `accept`, `review`, or `reject` |
| `required_checks_complete` | Prevents partial validation from passing |
| `checks` | Per-check outcome, severity, counts, and bounded examples |
| `coverage` | Per-instrument expected/observed coverage, when applicable |
| `created_at` | Audit timestamp |

For each check, store both its execution outcome and finding severity:

```text
check_id
outcome: pass | fail | error | not_applicable
severity: blocker | review | warning
metrics
bounded_examples
reason
```

`not_applicable` must include a reason and be permitted by policy. It is not a substitute for a missing required check.

### Bundle structure

Proposed accepted output:

```text
approved/<bundle_id>/
├── bars.parquet
├── quality-report.json
└── manifest.json
```

Proposed rejected output:

```text
evaluations/<evaluation_id>/
└── quality-report.json
```

The approved manifest should reference and hash:

- The published data
- The quality report
- The policy
- The upstream request and snapshot identities

Avoid circular hashing: the manifest hashes the report; the report does not need to hash that final manifest.

**Hash the same data representation that downstream consumers will read.** If serialization or normalization occurs after validation, revalidate the published representation or verify its equivalence under an explicitly defined contract.

**Checkpoint:** a rejected evaluation never creates an approved-bundle reference.

## Step 7 — Enforce the publication gate

Integrate the gate around your existing preparation and publication functions.

The following is **pseudocode**, not an existing API:

```python
candidate = load_and_prepare_snapshot(request, snapshot)

report = evaluate_quality(
    candidate=candidate,
    request=request,
    policy=policy,
)

report_ref = persist_quality_report(report)

if report.decision != "accept":
    return blocked_state(
        report_ref=report_ref,
        clear_approved_data_reference=True,
    )

bundle = publish_verified_bundle(
    candidate=candidate,
    quality_report=report,
    policy=policy,
)

return data_ready_state(
    data_ref=bundle.data_ref,
    quality_report_ref=bundle.quality_report_ref,
    manifest_ref=bundle.manifest_ref,
)
```

Additional requirements:

- Clear stale approved references on blocked outcomes.
- Publish the bundle completely before returning `data_ready`.
- Do not convert publication exceptions into success.
- Include policy and validator identity in cache/idempotency decisions.
- Never reuse old quality approval after the data or policy changes.

Keep conditional graph routing explicit:

```text
data_ready           → next enabled stage
data_review_required → stop
data_rejected        → stop
data_failed          → stop
```

**Checkpoint:** a downstream spy/mock is never called on blocked outcomes.

## Step 8 — Extend downstream verification

Before a Regime or Signal Agent loads data, the approved reader should verify:

1. Supported manifest and report schema versions.
2. Data and quality-report hashes.
3. Matching request and snapshot identities.
4. Quality decision is `accept`.
5. Required checks completed.
6. Applied policy is allowed for the current operation.
7. Available instruments, interval, and bar specification match the consumer’s requirements.

Do not trust a standalone string such as:

```python
state["status"] == "data_ready"
```

without validating the referenced evidence.

A hash is an integrity check relative to a trusted reference—not proof that the data is economically correct or that the manifest itself is trustworthy.

**Checkpoint:** modifying either the data or report after publication causes loading to fail.

## Step 9 — Add acceptance tests

Create this minimum test matrix:

| Test | Expected behavior |
|---|---|
| Approved reference dataset | Accepted bundle and `data_ready` |
| Missing required column | Reject |
| Duplicate instrument/timestamp | Reject under declared key policy |
| Invalid OHLC relationships | Reject |
| Non-finite required prices | Reject |
| Unresolvable required timezone/calendar | Block; no acceptance |
| Missing expected bars | Apply declared coverage policy |
| Legitimate market closure | Not classified as missing trading data |
| Insufficient warm-up | Block when required by the request |
| Extreme but plausible observation | Apply warning/review policy; no silent deletion |
| Validator raises an exception | `data_failed`; no approved bundle |
| Publication interrupted | No consumable approved bundle |
| Data/report tampered with | Reader rejects |
| Policy changes | Old approval not silently reused |
| Blocked evaluation | Next graph node never executes |
| Repeated identical preparation | Safe, verified reuse or deterministic republication |

Use your existing provenance-backed reference fixture. For negative tests, deliberately corrupt a copy and label it **test-only**; do not present altered records as genuine market observations.

Run the new modules after creating them:

```bash
python -m pytest \
  data_phase/tests/test_quality_checks.py \
  data_phase/tests/test_quality_gate.py \
  data_phase/tests/test_quality_artifacts.py \
  -v
```

Then run all existing suites.

**Checkpoint:** tests prove both acceptance and prevention of downstream execution.

## Step 10 — Update CI evidence

Keep your existing workflow installation and regression steps. Enhance the Phase 3 step to emit JUnit evidence:

```yaml
      - name: Phase 3 unit and integration tests
        run: |
          mkdir -p test-results
          python -m pytest data_phase/tests -v \
            --junitxml=test-results/data-phase.xml
```

Pytest supports generating JUnit XML with `--junitxml`, making it suitable for machine-readable regression evidence.[Pytest documentation](https://docs.pytest.org/en/stable/how-to/output.html#creating-junitxml-format-files)

Keep these outputs distinct:

```text
JUnit XML             → evidence about software tests
quality-report.json   → evidence about this dataset evaluation
manifest.json         → artifact identity and integrity references
```

Once the integration is implemented, the existing smoke test should also assert the produced quality decision and bundle validity—not merely a zero process exit code.

## Step 11 — Update the UI

Add four independent indicators to the Research Control Center:

| Indicator | Evidence |
|---|---|
| **Regression gate** | Test reports and process outcomes |
| **Data quality** | Verified quality report |
| **Artifact integrity** | Verified manifest and file hashes |
| **Execution authorization** | Existing request/supervisor controls |

Add a **Data Quality** tab containing:

- Decision and blocking reason
- Policy and validator versions
- Per-check results
- Per-instrument coverage
- Bounded examples of problematic records
- Report and manifest downloads
- Links to source snapshot identity

Until report verification is implemented, display:

```text
Data quality: Not independently verified
```

—not a green badge inferred from command completion.

## Documentation completion checklist

Update the documents with these explicit statements:

**Architecture**

> Data quality is an internal Data Agent gate. Only accepted, published, and verifiable bundles may reach downstream stages.

**Data Phase**

> Each dataset evaluation produces quality evidence. Rejection, review requirements, and validation errors block approved publication.

**Artifact contract**

> Approval is bound to exact data, request, policy, and validator identities. Legacy artifacts without quality evidence require revalidation.

**UI specification**

> Job completion, regression success, quality acceptance, integrity verification, and research acceptance are separate outcomes.

**Recommended implementation order:** audit existing checks → define contracts/policies → implement and test the gate → verify publication and downstream loading → update CI → connect the UI.
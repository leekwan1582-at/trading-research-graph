# Report Agent Specification

**The Report Agent is the final evidence-packaging stage: it gathers verified artifacts from the completed research run, renders a deterministic research report, and publishes human-readable outputs without changing any upstream result.**

**Specification:** `report-agent-v0.1.0`  
**Status:** Proposed specification only. It is not yet implemented, repository-verified, or packaged for download.

## 1. Purpose

The Report Agent answers:

> “How should this completed research run be presented as a coherent, auditable report for a human reader?”

It is a **presentation and evidence-packaging component**, not a research-decision engine.

### Included

- Load verified upstream bundles
- Assemble a run narrative from structured artifacts
- Render report outputs
- Link metrics, charts, tables, and evidence
- Publish immutable report artifacts
- Preserve traceability to source bundles

### Excluded

- Recomputing strategy metrics
- Reclassifying regimes
- Regenerating signals
- Recalibrating thresholds
- Rerunning backtests
- Changing the acceptance decision
- Manual editing of published research evidence
- Production deployment approval

**A finished report means the run was documented successfully—not that the strategy was accepted or production-ready.**

## 2. Pipeline placement

```text
Data Agent
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
    │
    ▼
Report Agent
┌─────────────────────────────────────┐
│ Verify final upstream artifacts     │
│ Load reporting policy/template      │
│ Build tables, charts, narratives    │
│ Render report bundle                │
│ Publish immutable outputs           │
└──────────────────┬──────────────────┘
                   │
             report_ready
```

The Report Agent should normally run **after** the Acceptance Gate so the published report can include the frozen research decision.

A future “intermediate research summary” mode can be versioned separately. It must not reuse the final report specification silently.

## 3. Core principle

The Report Agent must be **read-only with respect to research results**.

It may transform artifacts into:

- markdown
- HTML
- PDF-ready markdown
- tables
- static charts
- executive summaries
- evidence indexes

But it must not:

- modify metrics,
- recompute acceptance,
- hide failed checks,
- relabel rejected runs as accepted,
- omit required warnings.

The report is a **view over verified evidence**, not a second analysis engine.

## 4. Primary responsibilities

| Responsibility | Description |
|---|---|
| Integrity verification | Confirm upstream report inputs are authentic and consistent |
| Narrative assembly | Organize the run into understandable sections |
| Evidence presentation | Display metrics, diagnostics, and artifacts clearly |
| Decision presentation | Include acceptance outcome exactly as published |
| Traceability | Link every major statement to source artifacts |
| Publication | Write immutable report bundle outputs |

## 5. Inputs

The Report Agent consumes verified upstream bundles and frozen report configuration.

### Required inputs

| Input | Requirement |
|---|---|
| Acceptance bundle | Verified and complete |
| Diagnostics bundle | Verified and complete |
| Backtest bundle | Verified and complete |
| Calibration bundle | Verified and complete |
| Signal bundle | Verified and complete |
| Regime bundle, if used | Verified and complete |
| Data bundle | Verified and complete |
| Report configuration | Supported version and content hash |
| Execution context | Matching request, run, generation, fold scope, strategy identity |

### Input invariants

At minimum, the following must align:

- `request_sha256`
- `execution_plan_sha256`
- `run_id`
- `generation_id`
- `fold_id` or declared report scope
- `strategy_id`
- `signal_variant_id`
- `acceptance_policy_sha256`
- `acceptance_decision`
- `diagnostics_bundle_ref`
- `backtest_bundle_ref`

If the acceptance bundle references a different diagnostics bundle from the one supplied, report generation must block.

## 6. Reporting modes

The report mode must be explicit.

| Mode | Purpose |
|---|---|
| `final_research_report` | Full completed run with acceptance decision |
| `rejected_run_report` | Full run documenting rejection evidence |
| `review_required_report` | Completed run requiring human review |
| `technical_failure_report` | Optional future mode for failed incomplete runs |

For MVP, implement only:

- `final_research_report`
- `rejected_run_report`
- `review_required_report`

A rejected run still deserves a complete report if the run itself was completed successfully.

## 7. Report configuration contract

Illustrative configuration:

```yaml
schema_version: "1.0"
report_id: "research-report-v1"
mode: "final_research_report"

outputs:
  markdown: true
  html: true
  pdf_markdown: true

sections:
  executive_summary: true
  research_context: true
  data_quality: true
  regime_summary: true
  signal_summary: true
  calibration_summary: true
  backtest_summary: true
  diagnostics_summary: true
  acceptance_decision: true
  limitations_and_warnings: true
  evidence_index: true

charts:
  equity_curve: true
  drawdown_curve: true
  regime_distribution: true
  trade_pnl_histogram: false

redaction:
  hide_local_paths: true
  hide_internal_temp_ids: true
```

**The configuration defines presentation rules only.** It must not change research content.

### Validation rules

Reject:

- unsupported schema versions
- unknown mandatory section keys
- output requests not supported by the renderer
- attempts to suppress required acceptance or warning sections
- incompatible mode/section combinations

A config that hides a failed acceptance decision is invalid.

## 8. Required sections

The MVP report should contain these sections in deterministic order.

| Section | Content source |
|---|---|
| Title block | Execution context and strategy identity |
| Executive summary | Acceptance decision, scope, headline metrics |
| Research context | Request, fold, signal variant, execution model |
| Data quality | Data Agent and quality-gate evidence |
| Regime summary | Regime configuration and occupancy, if applicable |
| Signal summary | Signal variant, score semantics, eligibility coverage |
| Calibration summary | Search space, selected parameters, validation outcome |
| Backtest summary | P&L, drawdown, exposure, trade counts |
| Diagnostics summary | Stability, failure modes, warnings, fold comparisons |
| Acceptance decision | Exact decision and rule outcomes |
| Limitations and warnings | Known caveats and blocked interpretations |
| Evidence index | Artifact references, hashes, and lineage |

### Section requirements

- Every section must cite its source artifact or manifest reference in a machine-readable way inside the report bundle.
- Missing optional components, such as regimes in a regime-free strategy, must be described explicitly rather than omitted silently.
- Required failed or rejected outcomes must remain visible.

## 9. Executive summary rules

The executive summary must be concise and factual.

It should include:

- strategy and run identity
- evaluated scope
- acceptance decision
- top-line return and drawdown metrics
- trade count
- whether the run is accepted, rejected, or review-required
- one-sentence limitation statement

It must **not** include marketing language.

Examples of prohibited language:

- “promising”
- “robust”
- “production-ready”
- “high-confidence”
- “safe to deploy”

unless those exact terms are explicitly defined and supported elsewhere, which the MVP should avoid.

## 10. Narrative generation rules

The Report Agent may generate natural-language summaries, but only under constrained rules.

### Allowed behavior

- Rephrase structured metrics into readable prose
- Summarize rule outcomes
- Describe artifact relationships
- State known limitations already present in upstream evidence

### Prohibited behavior

- Inventing causal explanations not present in evidence
- Claiming statistical significance unless explicitly computed upstream
- Recommending deployment
- Reinterpreting a rejected result as “encouraging”
- Softening warnings or failures
- Concealing missing artifacts

For MVP, the narrative should be **template-driven**, not freeform generative text.

## 11. Visual outputs

The Report Agent may include rendered charts, but they must derive only from verified upstream outputs.

### Allowed charts

- equity curve
- drawdown curve
- rolling equity high-water mark
- regime occupancy chart
- trade outcome distribution
- calibration candidate comparison table/chart
- fold summary comparison

### Rules

- No chart may rely on recomputation of research metrics unless that computation is part of the verified reporting contract.
- Use upstream series where available.
- Any newly rendered chart must be reproducible from declared source artifact fields.
- Chart labels and units must match upstream definitions exactly.

If a required chart cannot be built because a source artifact is missing, the report must say so rather than silently dropping the section.

## 12. Acceptance-decision presentation

The report must reproduce the Acceptance Gate outcome exactly.

### Required fields

- decision: `accept`, `reject`, or `review`
- decision timestamp
- policy ID and policy hash
- rule-by-rule outcomes
- structured reason codes

### Presentation rules

- `reject` must appear clearly as rejection.
- `review` must appear clearly as review-required.
- `accept` must still include limitations.
- No color-coding or summary language may override the actual decision.

The report must never imply that acceptance equals production approval.

## 13. Scope and fold handling

The report must explicitly declare what scope it covers.

| Scope | Meaning |
|---|---|
| `single_fold` | One defined fold |
| `multi_fold` | Fixed set of folds |
| `aggregate_run` | Full declared research run |

For multi-fold reports, include:

- required fold identities
- aggregation method
- missing-fold policy
- dispersion metrics, if provided upstream

Do not silently aggregate partial results.

## 14. Output artifacts

### Required bundle

```text
report-bundles/<bundle_id>/
├── report.md
├── report.html
├── report-pdf.md
├── report-index.json
└── manifest.json
```

If HTML is not yet supported, the report configuration must disable it explicitly. Do not create placeholder empty files and mark them complete.

### `report.md`

Primary human-readable markdown report.

### `report.html`

Rendered HTML version, if supported.

### `report-pdf.md`

Markdown optimized for PDF conversion or printing.

### `report-index.json`

Machine-readable summary of:

- report mode
- included sections
- upstream bundle references
- output file hashes
- execution context
- report configuration hash

### `manifest.json`

Hashes all report outputs and references upstream manifests.

## 15. Traceability contract

Every report bundle must preserve a clear evidence chain.

### Minimum lineage

- data bundle ref/hash
- regime bundle ref/hash, if used
- signal bundle ref/hash
- calibration bundle ref/hash
- backtest bundle ref/hash
- diagnostics bundle ref/hash
- acceptance bundle ref/hash
- report configuration hash
- report renderer version

The report itself is not the source of truth. It is a rendering of these artifacts.

## 16. Blocking and failure conditions

### Block if

- acceptance bundle missing
- diagnostics bundle missing
- lineage mismatch across bundles
- unsupported report config version
- required section source missing
- report scope ambiguous
- acceptance decision absent for final mode

### Fail if

- rendering engine crashes
- chart rendering crashes after execution starts
- output publication incomplete
- manifest cannot be written
- deterministic template rendering is violated by invalid data shape

### Important distinction

| Outcome | Meaning |
|---|---|
| `blocked` | required inputs not suitable |
| `failed` | report generation started but did not complete |
| `report_ready` | outputs published successfully |

A rejected strategy can still produce `report_ready`.

## 17. State and routing

Suggested statuses:

| Status | Meaning |
|---|---|
| `report_running` | Rendering started |
| `report_ready` | Report bundle published |
| `report_blocked` | Missing/incompatible prerequisites |
| `report_failed` | Rendering/publication failed |

Conceptual state update:

```python
{
    "status": "report_ready",
    "report_bundle_ref": "...",
    "report_manifest_sha256": "...",
    "report_mode": "final_research_report",
}
```

These field names are proposed only.

### Terminal behavior

For MVP, `report_ready` should be the final successful pipeline state.

## 18. Determinism and reproducibility

The Report Agent must be deterministic.

### Required rules

- same verified inputs + same report config + same renderer version = same outputs
- section order is fixed
- number formatting rules are fixed
- chart ordering is fixed
- no nondeterministic text generation
- no random chart colors
- no hidden time-dependent content except explicit render timestamp fields

If the same inputs are rerendered, the report must match byte-for-byte except for explicitly versioned render metadata, if any.

## 19. Acceptance tests

Minimum required tests:

| Test | Expected outcome |
|---|---|
| Accepted reference run | `report_ready` with full bundle |
| Rejected completed run | `report_ready` with rejection clearly shown |
| Review-required run | `report_ready` with review status clearly shown |
| Missing acceptance bundle | `report_blocked` |
| Diagnostics from wrong backtest bundle | `report_blocked` |
| Unsupported config schema | `report_blocked` |
| Missing required chart source | `report_blocked` or section-marked unavailable per contract |
| Same inputs rerendered | identical output bundle |
| Interrupted publication | no consumable partial report bundle |
| Hidden-decision config attempt | rejected config |
| Any blocked/failed path | no final success reference written |

If HTML and markdown are both enabled, tests must verify they reference the same decision and scope.

## 20. Proposed package structure

```text
report_phase/
├── pyproject.toml
├── configs/
│   └── research-report-v1.yaml
├── templates/
│   ├── report.md.j2
│   └── report.html.j2
├── src/trading_report/
│   ├── contracts.py
│   ├── inputs.py
│   ├── sections.py
│   ├── charts.py
│   ├── renderer.py
│   ├── validation.py
│   ├── artifacts.py
│   ├── node.py
│   └── __main__.py
└── tests/
```

Suggested interfaces:

```python
load_verified_report_inputs(...)
validate_report_config(...)
build_report_sections(...)
render_markdown_report(...)
render_html_report(...)
publish_report_bundle(...)
load_verified_report_bundle(...)
report_agent(state, ...)
```

Use templated rendering rather than unconstrained text generation for the MVP.

## 21. UI and documentation updates

### Research Control Center

Add a **Generate report** operation showing:

- accepted scope
- upstream bundle identities
- report mode
- selected outputs
- section checklist
- downloadable artifacts

Display independently:

```text
Input integrity
Acceptance decision integrity
Report generation status
Production approval: Not evaluated
```

### Required documentation updates

| Artifact | Required update |
|---|---|
| Architecture | Add Report Agent as final presentation stage |
| Acceptance Gate spec | Clarify report consumes frozen final decision |
| Diagnostics spec | Clarify which outputs are report sources |
| Artifact contracts | Define report bundle and report index schemas |
| UI spec | Add final report generation and artifact downloads |
| CI workflow | Add report determinism and lineage tests |

## 22. Implementation milestones

1. Finalize report configuration schema.
2. Define report section contracts.
3. Implement verified input loading.
4. Implement template-driven markdown rendering.
5. Add chart rendering from verified artifact fields.
6. Add HTML and PDF-oriented markdown outputs.
7. Add bundle publication and determinism tests.

**Definition of done:** the Report Agent loads verified final research artifacts, preserves the exact acceptance decision and evidence chain, renders deterministic human-readable outputs, and publishes an immutable report bundle without recomputing or altering upstream research results.
**Test it in two parts: first compile the graph, then invoke it with the validated `queued_state`.** Compiling checks the graph structure; `graph.invoke(...)` actually executes the supervisor. [docs.langchain](https://docs.langchain.com/oss/python/langgraph/graph-api)

## 1. Activate your environment

In your **WSL/Ubuntu terminal**, run:

```bash
cd ~/code/trading-research
source supervisor_phase/.venv/bin/activate

python -c "import sys; print(sys.executable)"
```

Expected interpreter path:

```text
/home/YOUR_USERNAME/code/trading-research/supervisor_phase/.venv/bin/python
```

Keep the terminal in the **repository root**, not inside `supervisor_phase/`.

## 2. Check the imports

Your original imports:

```python
from .contracts import SupervisorState
from .supervisor import strategy_supervisor
```

are package-relative imports. For code pasted directly into a terminal, use the full package names instead; relative imports depend on the current module’s package context. [docs.python](https://docs.python.org/3/tutorial/modules.html)

Run:

```bash
python - <<'PY'
from langgraph.graph import START, END, StateGraph
from trading_supervisor.contracts import SupervisorState
from trading_supervisor.supervisor import strategy_supervisor

print('PASS: graph imports work')
PY
```

If you get `ModuleNotFoundError`, reinstall both local packages into the active environment:

```bash
python -m pip install -e './request_phase[dev]' -e './supervisor_phase[dev]'
```

## 3. Build and execute the graph

**Copy and paste this entire block into the terminal.** It prepares real intake output, builds the graph from your snippet, invokes the supervisor, and checks the result.

```bash
export LANGSMITH_TRACING=false
export LANGCHAIN_TRACING_V2=false

python - <<'PY'
import json
from copy import deepcopy
from pathlib import Path

from langgraph.graph import START, END, StateGraph

from trading_request.intake import accept_request
from trading_supervisor.contracts import (
    SupervisorState,
    canonical_hash,
    state_from_intake,
)
from trading_supervisor.supervisor import strategy_supervisor

# 1. Validate the example request.
accepted = accept_request(
    'examples/requests/valid.json',
    root=Path('request_phase'),
    allow_fixtures=True,
)

# 2. Prepare the supervisor's input.
queued_state = state_from_intake(
    accepted,
    allow_fixtures=True,
)

assert queued_state['status'] == 'queued'
before = deepcopy(queued_state)
print('PASS: validated supervisor input prepared')

# 3. Build your minimal graph.
builder = StateGraph(SupervisorState)
builder.add_node('strategy_supervisor', strategy_supervisor)
builder.add_edge(START, 'strategy_supervisor')
builder.add_edge('strategy_supervisor', END)

# 4. Compile: this does not execute the supervisor.
graph = builder.compile()
print('PASS: graph compiled')

# 5. Check that no specialist nodes are present.
expected_nodes = {START, 'strategy_supervisor', END}
assert set(graph.get_graph().nodes) == expected_nodes
print('PASS: graph contains only START -> supervisor -> END')

# 6. Execute the graph.
result = graph.invoke(
    queued_state,
    config={'recursion_limit': 10},
)
print('PASS: graph invocation completed')

# 7. Check the state transition and execution safeguards.
assert result['status'] == 'planned'
assert result['iteration'] == 0
assert result['execution_authorized'] is False
assert result['execution_plan']['mode'] == 'plan_only'
print('PASS: state changed from queued to planned')

# 8. Check that request fields and lineage are preserved.
for key, value in accepted['request'].items():
    assert result[key] == value, f'Request field changed: {key}'

assert result['lineage'] == queued_state['lineage']
assert result['execution_plan']['lineage'] == queued_state['lineage']
print('PASS: request and lineage preserved')

# 9. Check the plan and audit event.
assert (
    result['execution_plan']['max_iterations']
    == queued_state['max_iterations']
)
assert result['plan_sha256'] == canonical_hash(
    result['execution_plan']
)
assert len(result['events']) == 1
assert result['events'][0]['node'] == 'strategy_supervisor'
print('PASS: plan hash, iteration budget, and audit event verified')

# 10. Confirm the caller's input was not modified.
assert queued_state == before
print('PASS: original input was not modified')

print('\n--- Execution plan ---')
print(json.dumps(result['execution_plan'], indent=2))

print('\nSUCCESS: minimal supervisor graph test passed')
PY
```

This uses the supplied **metadata-only fixture**. It does not require real market data.

## 4. Confirm the output

With the supplied implementation, the output should include:

```text
PASS: validated supervisor input prepared
PASS: graph compiled
PASS: graph contains only START -> supervisor -> END
PASS: graph invocation completed
PASS: state changed from queued to planned
PASS: request and lineage preserved
PASS: plan hash, iteration budget, and audit event verified
PASS: original input was not modified

--- Execution plan ---
...JSON plan...

SUCCESS: minimal supervisor graph test passed
```

Immediately afterward, run:

```bash
echo $?
```

Expected:

```text
0
```

**The important transition is:**

```text
Input:  status = queued
Output: status = planned
```

The iteration remains `0` because no calibration or backtest has run.

## 5. Run the supplied tests

Test the existing graph factory and integration behavior:

```bash
python -m pytest supervisor_phase/tests/test_graph.py -v
```

LangGraph’s testing guidance supports compiling a graph in a test, invoking it with input state, and asserting the resulting state. [docs.langchain](https://docs.langchain.com/oss/python/langgraph/test)

Then run both complete suites:

```bash
python -m pytest request_phase/tests -v
python -m pytest supervisor_phase/tests -v
```

**Do not replace your existing `graph.py` with the terminal example.** The example tests the construction directly; `test_graph.py` tests the packaged implementation you will continue using.
import json
import os
import subprocess
import sys

from trading_data.graph import build_data_graph


def test_full_graph(queued, access):
    graph = build_data_graph(access=access)
    assert set(graph.get_graph().nodes) == {'__start__', 'strategy_supervisor', 'data_agent', '__end__'}
    result = graph.invoke(queued)
    assert result['status'] == 'data_ready'
    assert result['iteration'] == 0
    assert result['request_id'] == queued['request_id']
    assert len(result['events']) == 2
    assert result['data_artifact']['path'].endswith('/receipt.json')


def test_planned_only_graph(planned, access):
    graph = build_data_graph(access=access, include_supervisor=False)
    assert set(graph.get_graph().nodes) == {'__start__', 'data_agent', '__end__'}
    assert graph.invoke(planned)['status'] == 'data_ready'


def test_updates_execute_only_two_nodes(queued, access):
    updates = list(build_data_graph(access=access).stream(queued, stream_mode='updates'))
    assert [next(iter(update)) for update in updates] == ['strategy_supervisor', 'data_agent']


def run_cli(root, *args):
    return subprocess.run([sys.executable, '-m', 'trading_data', 'requests/valid.json', '--root', str(root), *args],
                          capture_output=True, text=True,
                          env={**os.environ, 'LANGSMITH_TRACING': 'false', 'LANGCHAIN_TRACING_V2': 'false'})


def test_cli_success(workspace):
    completed = run_cli(workspace, '--allow-fixtures', '--allow-local-data')
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)['status'] == 'data_ready'


def test_cli_local_permission_required(workspace):
    completed = run_cli(workspace, '--allow-fixtures')
    assert completed.returncode == 2
    assert json.loads(completed.stderr)['status'] == 'data_rejected'
    assert not (workspace / 'runs').exists()


def test_cli_fixture_permission_required(workspace):
    completed = run_cli(workspace, '--allow-local-data')
    assert completed.returncode == 2
    assert not (workspace / 'runs').exists()


def test_cli_missing_input(workspace):
    (workspace / 'data/raw/btc-test.parquet').unlink()
    completed = run_cli(workspace, '--allow-fixtures', '--allow-local-data')
    assert completed.returncode == 2
    assert 'missing' in completed.stderr

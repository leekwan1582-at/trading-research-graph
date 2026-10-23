from copy import deepcopy
from dataclasses import replace
import json
import socket

import pytest
import pyarrow as pa
import pyarrow.parquet as pq
from trading_supervisor.contracts import canonical_hash
from trading_data.agent import data_agent
from trading_data.storage import digest
from trading_data.validation import DataRejected


def test_prepares_artifacts_without_mutating_state(planned, access):
    before = deepcopy(planned)
    update = data_agent(planned, access=access)
    assert planned == before
    assert update['status'] == 'data_ready'
    assert update['execution_authorized'] is False
    assert len(update['events']) == 2
    assert [e['node'] for e in update['events']] == ['strategy_supervisor', 'data_agent']
    receipt_path = access.root / update['data_artifact']['path']
    assert digest(receipt_path.read_bytes()) == update['data_artifact']['sha256']
    receipt = json.loads(receipt_path.read_text())
    assert receipt['lineage'] == planned['lineage']
    assert receipt['rows'] == 2880
    assert receipt['trading_authorized'] is False
    bars = pq.ParquetFile(access.root / receipt['bars']['path']).read()
    assert bars.num_rows == 2880
    assert bars.column_names[-1] == 'bar_end_utc'


def test_idempotent_reexecution(planned, access):
    first = data_agent(planned, access=access)
    files = {str(p): (p.stat().st_ino, p.read_bytes()) for p in (access.root / 'runs/data').rglob('*') if p.is_file()}
    second = data_agent(planned, access=access)
    assert first == second
    assert files == {str(p): (p.stat().st_ino, p.read_bytes()) for p in (access.root / 'runs/data').rglob('*') if p.is_file()}


def test_requires_local_access(planned, access):
    with pytest.raises(DataRejected, match='explicit'):
        data_agent(planned, access=replace(access, allow_local_data=False))
    assert not (access.root / 'runs').exists()


def test_fixture_requires_opt_in(planned, access):
    with pytest.raises(DataRejected, match='fixture'):
        data_agent(planned, access=replace(access, allow_fixtures=False))


@pytest.mark.parametrize('key,value', [
    ('status', 'queued'), ('status', 'data_ready'), ('iteration', 1), ('iteration', False),
    ('execution_authorized', True), ('events', []), ('data_artifact', {}), ('data_quality', {}),
    ('plan_sha256', '0' * 64), ('max_iterations', 4),
])
def test_invalid_planned_state(planned, access, key, value):
    planned[key] = value
    with pytest.raises(ValueError):
        data_agent(planned, access=access)
    assert not (access.root / 'runs').exists()


@pytest.mark.parametrize('kind', ['manifest', 'spec', 'source'])
def test_changed_source_inputs_rejected(planned, access, kind):
    relative = {'manifest': 'data/manifests/btc-spot-1m-real-test-v1.json',
                'spec': 'specs/btc-data-test.json', 'source': 'data/raw/btc-test.parquet'}[kind]
    path = access.root / relative
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(DataRejected, match='changed|hash mismatch'):
        data_agent(planned, access=access)
    assert not (access.root / 'runs').exists()


def test_byte_cap(planned, access):
    with pytest.raises(DataRejected, match='byte cap'):
        data_agent(planned, access=replace(access, max_input_bytes=100))


def test_row_cap(planned, access):
    with pytest.raises(DataRejected, match='row cap'):
        data_agent(planned, access=replace(access, max_input_rows=100))


def test_no_network(planned, access, monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    assert data_agent(planned, access=access)['status'] == 'data_ready'


def test_bad_bars_do_not_publish_receipt(planned, access):
    path = access.root / 'data/raw/btc-test.parquet'
    table = pq.ParquetFile(path).read()
    pq.write_table(pa.concat_tables([table.slice(0, 500), table.slice(501)]), path)
    catalog_path = access.root / 'data/catalog/btc-spot-1m-real-test-v1.json'
    catalog = json.loads(catalog_path.read_text())
    catalog['parquet_sha256'] = digest(path.read_bytes())
    catalog_path.write_text(json.dumps(catalog))
    with pytest.raises(DataRejected, match='missing bars'):
        data_agent(planned, access=access)
    assert not (access.root / 'runs').exists()


def test_plan_constraint_mismatch(planned, access):
    planned['execution_plan']['universe'] = ['ES']
    planned['plan_sha256'] = canonical_hash(planned['execution_plan'])
    with pytest.raises(DataRejected, match='constraints'):
        data_agent(planned, access=access)


def test_catalog_bound_to_manifest(planned, access):
    path = access.root / 'data/catalog/btc-spot-1m-real-test-v1.json'
    value = json.loads(path.read_text())
    value['intake_manifest_sha256'] = '0' * 64
    path.write_text(json.dumps(value))
    with pytest.raises(DataRejected, match='not bound'):
        data_agent(planned, access=access)


def test_interval_matches_spec(planned, access):
    path = access.root / 'data/catalog/btc-spot-1m-real-test-v1.json'
    value = json.loads(path.read_text())
    value['interval_seconds'] = 300
    path.write_text(json.dumps(value))
    with pytest.raises(DataRejected, match='bar_frequency'):
        data_agent(planned, access=access)

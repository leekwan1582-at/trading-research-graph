import json
from importlib.metadata import version

import pyarrow as pa
import pyarrow.parquet as pq
from trading_supervisor.contracts import canonical_hash

from .contracts import AcceptedRequest, CatalogEntry, DataAccess, DataState
from .storage import canonical, confined, digest, limited_read, publish
from .validation import DataRejected, VALIDATOR_VERSION, validate_bars

REQUEST_KEYS = ('schema_version', 'request_id', 'strategy_spec_uri', 'dataset_snapshot_id',
                'universe', 'start', 'end', 'max_iterations')


def data_agent(state: DataState, *, access: DataAccess) -> dict:
    if not access.allow_local_data:
        raise DataRejected('local-data execution requires explicit allow_local_data=True')
    if state.get('status') != 'planned' or state.get('execution_authorized') is not False:
        raise DataRejected('data agent requires planned, research-only state')
    if type(state.get('iteration')) is not int or state['iteration'] != 0:
        raise DataRejected('data phase requires iteration zero')
    if 'data_artifact' in state or 'data_quality' in state:
        raise DataRejected('fresh data preparation must not contain a prior artifact')
    request = AcceptedRequest.model_validate({key: state[key] for key in REQUEST_KEYS})
    normalized = request.model_dump(mode='json')
    plan = state.get('execution_plan', {})
    lineage = state.get('lineage', {})
    if canonical_hash(plan) != state.get('plan_sha256'):
        raise DataRejected('plan hash mismatch')
    if plan.get('lineage') != lineage or canonical_hash(normalized) != lineage.get('request_sha256'):
        raise DataRejected('request/plan lineage mismatch')
    expected = {
        'request_id': request.request_id, 'dataset_snapshot_id': request.dataset_snapshot_id,
        'universe': request.universe, 'max_iterations': request.max_iterations,
        'window': {'start': normalized['start'], 'end': normalized['end'], 'date_bounds': 'inclusive'},
        'mode': 'plan_only', 'execution_authorized': False,
    }
    if any(plan.get(key) != value for key, value in expected.items()):
        raise DataRejected('plan constraints do not match the accepted request')
    if not any(stage.get('name') == 'data' and stage.get('depends_on') == [] for stage in plan.get('stages', [])):
        raise DataRejected('plan does not include the supported data stage')
    events = state.get('events')
    if not isinstance(events, list) or len(events) != 1 or events[0].get('node') != 'strategy_supervisor':
        raise DataRejected('expected the Phase 2 supervisor audit event')

    root = access.root.resolve(strict=True)
    manifest = limited_read(confined(root, f'data/manifests/{request.dataset_snapshot_id}.json'), 1_000_000)
    if digest(manifest) != lineage.get('snapshot_manifest_sha256'):
        raise DataRejected('intake manifest changed since planning')
    spec_blob = limited_read(confined(root, request.strategy_spec_uri), 1_000_000)
    if digest(spec_blob) != lineage.get('strategy_spec_sha256'):
        raise DataRejected('strategy specification changed since planning')
    catalog_blob = limited_read(confined(root, f'data/catalog/{request.dataset_snapshot_id}.json'), 1_000_000)
    catalog = CatalogEntry.model_validate_json(catalog_blob)
    if catalog.snapshot_id != request.dataset_snapshot_id or catalog.intake_manifest_sha256 != digest(manifest):
        raise DataRejected('data catalog not bound to accepted snapshot manifest')
    if catalog.fixture_only != lineage.get('fixture_only'):
        raise DataRejected('fixture flag differs across phase boundaries')
    if catalog.fixture_only and not access.allow_fixtures:
        raise DataRejected('test fixture requires allow_fixtures=True')
    frequency = {'1min': 60, '5min': 300, '15min': 900, '1h': 3600, '1d': 86400}
    if frequency.get(json.loads(spec_blob).get('bar_frequency')) != catalog.interval_seconds:
        raise DataRejected('strategy bar_frequency unsupported or inconsistent with catalog')
    if 86400 % catalog.interval_seconds:
        raise DataRejected('bar interval must divide the UTC day in this milestone')
    source = limited_read(confined(root, catalog.parquet_path), access.max_input_bytes)
    if digest(source) != catalog.parquet_sha256:
        raise DataRejected('source Parquet hash mismatch')
    reader = pq.ParquetFile(pa.BufferReader(source))
    if reader.metadata.num_rows > access.max_input_rows:
        raise DataRejected('source exceeds row cap')
    bars, quality = validate_bars(reader.read(), catalog, start=normalized['start'], end=normalized['end'], universe=request.universe)
    quality['fixture_only'] = catalog.fixture_only
    software = {'data_agent': VALIDATOR_VERSION, 'pyarrow': version('pyarrow'), 'pandas': version('pandas')}
    identity = {
        'plan_sha256': state['plan_sha256'], 'catalog_sha256': digest(catalog_blob),
        'source_sha256': digest(source), 'software': software,
    }
    artifact_id = digest(canonical(identity))
    base = f'runs/data/{artifact_id}'
    buffer = pa.BufferOutputStream()
    pq.write_table(bars, buffer, compression='zstd', version='2.6', store_schema=True)
    parquet_blob = buffer.getvalue().to_pybytes()
    # Publish the commit receipt LAST; consumers must resolve artifacts via it.
    parquet_ref = publish(root, f'{base}/bars.parquet', parquet_blob)
    quality_ref = publish(root, f'{base}/quality.json', canonical(quality))
    receipt = {
        'schema_version': '1', 'artifact_id': artifact_id, 'identity': identity,
        'source_catalog': catalog.model_dump(mode='json'), 'lineage': lineage,
        'bars': parquet_ref, 'quality': quality_ref, 'rows': bars.num_rows,
        'timestamp_convention': 'bar_open_utc',
        'availability_note': 'OHLCV is not available at bar open; bar_end_utc is an interval boundary, not a verified receive time.',
        'trading_authorized': False,
    }
    receipt_ref = publish(root, f'{base}/receipt.json', canonical(receipt))
    return {
        'status': 'data_ready', 'data_artifact': receipt_ref, 'data_quality': quality,
        'execution_authorized': False,
        # Phase 2 uses replacement semantics: preserve the existing event explicitly.
        'events': events + [{
            'event_id': digest(canonical({'node': 'data_agent', 'artifact_id': artifact_id})),
            'node': 'data_agent', 'iteration': 0,
            'message': f'Prepared {bars.num_rows} validated rows; downstream workers not executed',
        }],
    }

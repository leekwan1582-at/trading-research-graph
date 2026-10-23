"""Explicit local test-workspace seeder. Does not fetch data or replace Phase 1 examples."""
import argparse
import json
from pathlib import Path

from .storage import canonical, digest, publish


def seed(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    fixtures = Path(__file__).resolve().parents[2] / 'tests' / 'fixtures'
    provenance = json.loads((fixtures / 'PROVENANCE.json').read_text())
    source = (fixtures / 'btcusdt-20240101-02.parquet').read_bytes()
    if digest(source) != provenance['parquet_sha256']:
        raise ValueError('bundled fixture hash mismatch')
    snapshot = 'btc-spot-1m-real-test-v1'
    manifest = {
        'schema_version': '1', 'snapshot_id': snapshot, 'fixture_only': True,
        'instruments': ['BTCUSDT'], 'available_start': '2024-01-01', 'available_end': '2024-01-02',
    }
    spec = {
        'schema_version': '1', 'strategy_id': 'btc-data-pipeline-test', 'bar_frequency': '1min',
        'research_question': 'Test deterministic local market-data preparation; no strategy inference.',
    }
    request = {
        'schema_version': '1', 'request_id': 'btc-data-phase-test-001',
        'strategy_spec_uri': 'specs/btc-data-test.json', 'dataset_snapshot_id': snapshot,
        'universe': ['BTCUSDT'], 'start': '2024-01-01', 'end': '2024-01-02', 'max_iterations': 3,
    }
    catalog = {
        'schema_version': '1', 'snapshot_id': snapshot, 'parquet_path': 'data/raw/btc-test.parquet',
        'parquet_sha256': digest(source), 'intake_manifest_sha256': digest(canonical(manifest)),
        'fixture_only': True, 'instruments': ['BTCUSDT'], 'interval_seconds': 60,
        'timestamp_convention': 'bar_open_utc', 'calendar_policy': 'continuous_24x7',
        'price_policy': 'positive', 'source_url': provenance['source_url'],
        'source_archive_sha256': provenance['source_archive_sha256'], 'provenance_note': provenance['note'],
    }
    publish(root, 'data/raw/btc-test.parquet', source)
    for path, value in {
        f'data/manifests/{snapshot}.json': manifest, 'specs/btc-data-test.json': spec,
        'requests/valid.json': request, f'data/catalog/{snapshot}.json': catalog,
    }.items():
        publish(root, path, canonical(value))
    return root.resolve()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('data_phase/runs/demo'))
    args = parser.parse_args()
    print(seed(args.root))

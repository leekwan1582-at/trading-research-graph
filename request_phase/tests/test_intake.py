import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from trading_request.intake import accept_request


@pytest.fixture
def project(tmp_path):
    source = Path(__file__).resolve().parents[1]
    for name in ('examples/requests/valid.json', 'examples/specs/es_meanrev.json',
                 'data/manifests/demo-es-snapshot-v1.json'):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((source / name).read_bytes())
    payload = json.loads((tmp_path / 'examples/requests/valid.json').read_text())
    return tmp_path, payload


def save(root, payload):
    name = 'examples/requests/current.json'
    (root / name).write_text(json.dumps(payload))
    return name


def cli(root, name, *args):
    return subprocess.run([sys.executable, '-m', 'trading_request', name,
                           '--root', str(root), *args], capture_output=True, text=True)


def accept(root, payload):
    return accept_request(save(root, payload), root=root, allow_fixtures=True)


def test_valid_request(project):
    root, payload = project
    result = accept(root, payload)
    assert result['status'] == 'request_validated'
    assert result['validation_scope'] == 'metadata_only'
    assert result['fixture_only'] is True
    assert result['initial_state']['iteration'] == 0
    assert result['initial_state']['status'] == 'queued'
    assert result['initial_state']['request_id'] == payload['request_id']
    assert not (root / 'runs').exists()


@pytest.mark.parametrize('field', ['request_id', 'strategy_spec_uri',
    'dataset_snapshot_id', 'universe', 'start', 'end'])
def test_missing_required(project, field):
    root, payload = project
    del payload[field]
    with pytest.raises(ValidationError):
        accept(root, payload)


@pytest.mark.parametrize('field,value', [
    ('request_id', ''), ('request_id', '../escape'),
    ('dataset_snapshot_id', '../escape'), ('strategy_spec_uri', '  '),
    ('universe', []), ('universe', [' ']), ('universe', ['ES', 'ES']),
    ('max_iterations', 0), ('max_iterations', 21),
    ('max_iterations', '3'), ('max_iterations', True),
    ('start', 'invalid-date'), ('start', '2026-01-01'),
    ('end', '2020-01-01'), ('schema_version', '2'),
])
def test_invalid_values(project, field, value):
    root, payload = project
    payload[field] = value
    with pytest.raises(ValidationError):
        accept(root, payload)


def test_unknown_field(project):
    root, payload = project
    payload['max_iteration'] = 3
    with pytest.raises(ValidationError, match='Extra inputs'):
        accept(root, payload)


def test_default_budget(project):
    root, payload = project
    del payload['max_iterations']
    assert accept(root, payload)['request']['max_iterations'] == 3


def test_fixture_opt_in(project):
    root, payload = project
    with pytest.raises(ValueError, match='fixture snapshot rejected'):
        accept_request(save(root, payload), root=root)


@pytest.mark.parametrize('field,value', [
    ('strategy_spec_uri', 'examples/specs/missing.json'),
    ('dataset_snapshot_id', 'missing-snapshot')])
def test_missing_reference(project, field, value):
    root, payload = project
    payload[field] = value
    with pytest.raises(FileNotFoundError):
        accept(root, payload)


@pytest.mark.parametrize('field,value', [
    ('universe', ['NQ']), ('start', '2019-12-31'), ('end', '2026-01-01')])
def test_coverage_mismatch(project, field, value):
    root, payload = project
    payload[field] = value
    with pytest.raises(ValueError):
        accept(root, payload)


def test_manifest_id_mismatch(project):
    root, payload = project
    path = root / 'data/manifests/demo-es-snapshot-v1.json'
    manifest = json.loads(path.read_text())
    manifest['snapshot_id'] = 'different'
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='snapshot ID'):
        accept(root, payload)


@pytest.mark.parametrize('value', ['../outside.json', '/etc/passwd'])
def test_path_escape(project, value):
    root, payload = project
    payload['strategy_spec_uri'] = value
    with pytest.raises(ValueError):
        accept(root, payload)


def test_symlink_escape(project):
    root, payload = project
    outside = root.parent / (root.name + '-outside.json')
    outside.write_text('{}')
    (root / 'outside-link.json').symlink_to(outside)
    payload['strategy_spec_uri'] = 'outside-link.json'
    with pytest.raises(ValueError, match='escapes project root'):
        accept(root, payload)


def test_hash_stability(project):
    root, payload = project
    first = accept(root, payload)
    assert first == accept(root, dict(reversed(list(payload.items()))))
    payload['max_iterations'] = 4
    assert first['request_sha256'] != accept(root, payload)['request_sha256']
    assert len(first['strategy_spec_sha256']) == 64


def test_valid_cli(project):
    root, payload = project
    result = cli(root, save(root, payload), '--allow-fixtures', '--output', 'runs/receipt.json')
    assert result.returncode == 0, result.stderr
    receipt = json.loads((root / 'runs/receipt.json').read_text())
    assert receipt['status'] == 'request_validated'
    assert json.loads(result.stdout) == receipt


def test_invalid_cli_has_no_receipt(project):
    root, payload = project
    payload['max_iterations'] = 0
    result = cli(root, save(root, payload), '--allow-fixtures', '--output', 'runs/receipt.json')
    assert result.returncode == 2
    assert json.loads(result.stderr)['status'] == 'rejected'
    assert result.stdout == ''
    assert not (root / 'runs/receipt.json').exists()


def test_no_overwrite(project):
    root, payload = project
    name = save(root, payload)
    args = ('--allow-fixtures', '--output', 'runs/receipt.json')
    assert cli(root, name, *args).returncode == 0
    original = (root / 'runs/receipt.json').read_bytes()
    assert cli(root, name, *args).returncode == 2
    assert (root / 'runs/receipt.json').read_bytes() == original


def test_malformed_json(project):
    root, _ = project
    (root / 'broken.json').write_text('{not-json')
    result = cli(root, 'broken.json')
    assert result.returncode == 2
    assert json.loads(result.stderr)['status'] == 'rejected'


def test_output_escape(project):
    root, payload = project
    result = cli(root, save(root, payload), '--allow-fixtures', '--output', '../escape.json')
    assert result.returncode == 2
    assert 'escapes project root' in result.stderr

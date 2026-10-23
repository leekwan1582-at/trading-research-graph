import json
from pathlib import Path

import pytest
from trading_data.storage import confined, publish
from trading_data.validation import DataRejected
from trading_data.agent import data_agent


def test_safe_publication_reuses_identical_bytes(tmp_path):
    first = publish(tmp_path, 'artifacts/a.json', b'{}')
    inode = (tmp_path / first['path']).stat().st_ino
    assert publish(tmp_path, 'artifacts/a.json', b'{}') == first
    assert (tmp_path / first['path']).stat().st_ino == inode
    assert not list(tmp_path.rglob('.pending-*'))


def test_conflicting_publication_does_not_overwrite(tmp_path):
    publish(tmp_path, 'a', b'original')
    with pytest.raises(DataRejected, match='conflict|byte cap'):
        publish(tmp_path, 'a', b'changed')
    assert (tmp_path / 'a').read_bytes() == b'original'
    assert not list(tmp_path.rglob('.pending-*'))


@pytest.mark.parametrize('path', ['../escape', '/tmp/absolute'])
def test_confined_paths(tmp_path, path):
    with pytest.raises(DataRejected): confined(tmp_path, path)


def test_symlink_escape(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + '-outside')
    outside.mkdir()
    (tmp_path / 'link').symlink_to(outside, target_is_directory=True)
    with pytest.raises(DataRejected, match='escapes'):
        publish(tmp_path, 'link/not-written', b'no')
    assert not (outside / 'not-written').exists()


def test_retry_after_missing_commit_receipt(planned, access):
    first = data_agent(planned, access=access)
    path = access.root / first['data_artifact']['path']
    path.unlink()
    again = data_agent(planned, access=access)
    assert first == again
    assert path.exists()


def test_corrupt_artifact_is_rejected(planned, access):
    first = data_agent(planned, access=access)
    receipt = json.loads((access.root / first['data_artifact']['path']).read_text())
    bars = access.root / receipt['bars']['path']
    bars.write_bytes(b'corrupt')
    with pytest.raises(DataRejected, match='conflict'):
        data_agent(planned, access=access)
    assert bars.read_bytes() == b'corrupt'


def test_verified_reader(planned, access):
    from trading_data.reader import load_prepared
    update = data_agent(planned, access=access)
    bars, quality, receipt = load_prepared(access.root, update['data_artifact'])
    assert bars.num_rows == receipt['rows'] == quality['selected_rows'] == 2880


@pytest.mark.parametrize('target', ['receipt', 'bars', 'quality'])
def test_reader_rejects_corruption(planned, access, target):
    from trading_data.reader import load_prepared
    update = data_agent(planned, access=access)
    receipt_ref = update['data_artifact']
    receipt = json.loads((access.root / receipt_ref['path']).read_text())
    reference = receipt_ref if target == 'receipt' else receipt[target]
    (access.root / reference['path']).write_bytes(b'corrupt')
    with pytest.raises(DataRejected, match='hash or size mismatch'):
        load_prepared(access.root, receipt_ref)

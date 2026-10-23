from pathlib import Path

import pyarrow.parquet as pq
import pytest
from trading_request.intake import accept_request
from trading_supervisor.contracts import state_from_intake
from trading_supervisor.supervisor import strategy_supervisor
from trading_data.contracts import CatalogEntry, DataAccess
from trading_data.seed_demo import seed


@pytest.fixture
def workspace(tmp_path):
    return seed(tmp_path / 'project')


@pytest.fixture
def queued(workspace):
    accepted = accept_request('requests/valid.json', root=workspace, allow_fixtures=True)
    return state_from_intake(accepted, allow_fixtures=True)


@pytest.fixture
def planned(queued):
    return {**queued, **strategy_supervisor(queued)}


@pytest.fixture
def access(workspace):
    return DataAccess(root=workspace, allow_local_data=True, allow_fixtures=True)


@pytest.fixture
def catalog(workspace):
    return CatalogEntry.model_validate_json((workspace / 'data/catalog/btc-spot-1m-real-test-v1.json').read_bytes())


@pytest.fixture
def table(workspace):
    return pq.ParquetFile(workspace / 'data/raw/btc-test.parquet').read()

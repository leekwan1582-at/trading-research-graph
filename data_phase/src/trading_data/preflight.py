import inspect
from pathlib import Path
import sys
import tempfile
from typing import Annotated, get_origin, get_type_hints

from trading_request.intake import accept_request
from trading_supervisor.contracts import SupervisorState, state_from_intake
from trading_supervisor.supervisor import strategy_supervisor

from .agent import data_agent
from .contracts import DataAccess, DataState
from .seed_demo import seed


def main():
    hints = get_type_hints(SupervisorState, include_extras=True)
    if get_origin(hints.get('events')) is Annotated:
        raise ValueError('events uses a reducer: adapt Data Agent event return semantics before proceeding')
    required = {'status', 'iteration', 'lineage', 'events', 'execution_plan', 'execution_authorized'}
    if not required.issubset(DataState.__annotations__):
        raise ValueError('upstream SupervisorState differs: missing fields; review adapter')
    with tempfile.TemporaryDirectory(prefix='data-preflight-') as tmp:
        root = seed(Path(tmp) / 'project')
        accepted = accept_request('requests/valid.json', root=root, allow_fixtures=True)
        queued = state_from_intake(accepted, allow_fixtures=True)
        planned = {**queued, **strategy_supervisor(queued)}
        update = data_agent(planned, access=DataAccess(root, allow_local_data=True, allow_fixtures=True))
        assert update['status'] == 'data_ready'
    print('PASS: installed Phase 1 and Phase 2 contracts match this Phase 3 adapter')
    for function in (accept_request, state_from_intake, strategy_supervisor):
        print(f'{function.__name__}: {inspect.getfile(function)}')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, TypeError, KeyError, AssertionError, OSError) as exc:
        print(f'STOP: upstream compatibility check failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(2)

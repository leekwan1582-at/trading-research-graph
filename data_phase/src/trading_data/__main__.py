import argparse
import json
import os
from pathlib import Path
import sys

from pydantic import ValidationError
from trading_request.intake import accept_request
from trading_supervisor.contracts import state_from_intake

from .contracts import DataAccess
from .graph import build_data_graph


def main():
    parser = argparse.ArgumentParser(description='Prepare and validate local Parquet; no broker or model calls')
    parser.add_argument('request')
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--allow-local-data', action='store_true')
    parser.add_argument('--allow-fixtures', action='store_true')
    parser.add_argument('--max-input-bytes', type=int, default=32 * 1024 * 1024)
    parser.add_argument('--max-input-rows', type=int, default=2_000_000)
    args = parser.parse_args()
    try:
        access = DataAccess(root=args.root, allow_local_data=args.allow_local_data,
                            allow_fixtures=args.allow_fixtures, max_input_bytes=args.max_input_bytes,
                            max_input_rows=args.max_input_rows)
        accepted = accept_request(args.request, root=args.root, allow_fixtures=args.allow_fixtures)
        queued = state_from_intake(accepted, allow_fixtures=args.allow_fixtures)
        result = build_data_graph(access=access).invoke(queued, config={'callbacks': [], 'recursion_limit': 10})
    except (ValueError, OSError, KeyError) as exc:
        message = str(exc.errors(include_input=False, include_url=False)) if isinstance(exc, ValidationError) else str(exc)
        print(json.dumps({'status': 'data_rejected', 'error': message}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    os.environ['LANGSMITH_TRACING'] = 'false'
    os.environ['LANGCHAIN_TRACING_V2'] = 'false'
    raise SystemExit(main())

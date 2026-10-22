from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .intake import accept_request


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a trading research request; no trading.")
    parser.add_argument("request", help="JSON path relative to --root")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, help="Optional NEW JSON file, relative to --root")
    parser.add_argument("--allow-fixtures", action="store_true")
    args = parser.parse_args()
    try:
        result = accept_request(
            args.request, root=args.root, allow_fixtures=args.allow_fixtures
        )
        if args.output is not None:
            root = args.root.resolve(strict=True)
            if args.output.is_absolute():
                raise ValueError("output must be project-relative")
            output = (root / args.output).resolve()
            if not output.is_relative_to(root):
                raise ValueError("output path escapes project root")
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(result, indent=2) + "\n")
    except (ValidationError, OSError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            message = str(exc.errors(include_input=False, include_url=False))
        else:
            message = str(exc)
        print(json.dumps({"status": "rejected", "error": message}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

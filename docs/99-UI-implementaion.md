Below is a **local-first MVP** with three separate processes:

```text
Streamlit UI → FastAPI control API → SQLite job queue → Python worker
                                                        │
                                                        ├─ Regression tests
                                                        ├─ Request validation
                                                        ├─ Supervisor planning
                                                        └─ Data Agent demo
```

**Important:** I cannot inspect the complete contents of `99-UI.md` in this turn, so this implementation follows the architecture and safeguards discussed above—not a verified line-by-line implementation of the attachment. I also cannot execute or package the code here; **no tests are claimed to have passed**. 
This version deliberately supports **local testing and fixture-based execution only**. It does not enable unrestricted commands, live-data ingestion, or automatic strategy acceptance.

# 1. Create the extension

Run from your repository root:

```bash
cd ~/trading-research-graph

git switch -c feat/research-control-center

mkdir -p control_center/tests
touch control_center/__init__.py
```

Create these files using VS Code:

```text
trading-research-graph/
├── control_center/
│   ├── __init__.py
│   ├── requirements.txt
│   ├── control.py
│   ├── ui.py
│   └── tests/
│       └── test_control.py
├── request_phase/
├── supervisor_phase/
└── data_phase/
```

Your existing phase implementations remain unchanged.

# 2. Add dependencies

Create **`control_center/requirements.txt`**:

```text
fastapi>=0.115,<1
uvicorn>=0.30,<1
streamlit>=1.40,<2
httpx>=0.27,<1
pytest>=8,<10
```

These are compatibility ranges, **not a tested lockfile**. After installation and successful testing, capture your resolved environment separately.

# 3. Add the API and worker

Create **`control_center/control.py`**:

```python
import argparse
import fcntl
import hashlib
import hmac
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field


ROOT = Path(
    os.environ.get("RESEARCH_REPO_ROOT", os.getcwd())
).resolve()

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}

MAX_FILE_BYTES = 16 * 1024 * 1024

SUITES = [
    ("phase1", "request_phase/tests"),
    ("phase2", "supervisor_phase/tests"),
    ("phase3", "data_phase/tests"),
]


def state_dir():
    return ROOT / ".research-control"


def job_dir(job_id):
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise ValueError("Invalid job ID")
    return state_dir() / "jobs" / job_id


@contextmanager
def database():
    connection = sqlite3.connect(
        state_dir() / "control.sqlite3",
        timeout=30,
    )
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize():
    state_dir().mkdir(parents=True, exist_ok=True, mode=0o700)
    (state_dir() / "jobs").mkdir(exist_ok=True)

    with database() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                spec TEXT NOT NULL,
                created REAL NOT NULL,
                updated REAL NOT NULL,
                cancel INTEGER NOT NULL DEFAULT 0,
                result TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                at REAL NOT NULL,
                stage TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)

    token_path = state_dir() / "api-token"
    try:
        descriptor = os.open(
            token_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(uuid.uuid4().hex + uuid.uuid4().hex)


def event(job_id, stage, status, detail=None):
    with database() as db:
        db.execute(
            """
            INSERT INTO events(job_id, at, stage, status, detail)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                job_id,
                time.time(),
                stage,
                status,
                json.dumps(detail or {}),
            ),
        )


def heartbeat():
    with database() as db:
        db.execute(
            """
            INSERT INTO metadata(key, value)
            VALUES ('worker_heartbeat', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (str(time.time()),),
        )


def get_job(job_id):
    job_dir(job_id)
    with database() as db:
        row = db.execute(
            "SELECT * FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()

    if row is None:
        raise KeyError(job_id)

    result = dict(row)
    result["spec"] = json.loads(result["spec"])
    result["result"] = json.loads(result["result"])
    result["cancel"] = bool(result["cancel"])
    return result


def request_choices():
    base = ROOT / "request_phase/examples/requests"
    if not base.is_dir():
        return []

    choices = []
    for path in sorted(base.glob("*.json")):
        if (
            path.is_file()
            and not path.is_symlink()
            and path.resolve().is_relative_to(base.resolve())
        ):
            choices.append(path.relative_to(ROOT).as_posix())
    return choices


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    submission_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        pattern=r"^[0-9a-f]{32}$",
    )

    target: Literal["tests", "request", "plan", "data_demo"]
    request_path: str = ""
    allow_fixtures: bool = False
    allow_local_data: bool = False


def submit(specification):
    target = specification.target

    if target in {"request", "plan"}:
        if specification.request_path not in request_choices():
            raise HTTPException(
                422,
                "Choose an existing request from the workspace catalog.",
            )
    elif specification.request_path:
        raise HTTPException(
            422,
            "This operation does not accept a request path.",
        )

    if target == "data_demo":
        if not (
            specification.allow_fixtures
            and specification.allow_local_data
        ):
            raise HTTPException(
                422,
                "Data demo requires explicit fixture and local-data consent.",
            )

    job_id = specification.submission_id
    payload = specification.model_dump(exclude={"submission_id"})
    encoded = json.dumps(payload, sort_keys=True)
    now = time.time()

    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT spec FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()

        if existing:
            if existing["spec"] != encoded:
                raise HTTPException(
                    409,
                    "Submission ID already belongs to a different request.",
                )
        else:
            db.execute(
                """
                INSERT INTO jobs(id, status, spec, created, updated)
                VALUES (?, 'queued', ?, ?, ?)
                """,
                (job_id, encoded, now, now),
            )

    return get_job(job_id)


def cancelled(job_id):
    return get_job(job_id)["cancel"]


def source_fingerprint():
    digest = hashlib.sha256()
    directories = [
        "request_phase",
        "supervisor_phase",
        "data_phase",
        "control_center",
        ".github",
    ]
    excluded = {
        ".venv", "__pycache__", ".pytest_cache",
        ".mypy_cache", ".ruff_cache", ".git",
        "runs", "build", "dist",
    }
    extensions = {
        ".py", ".toml", ".txt", ".json",
        ".yaml", ".yml", ".ini", ".cfg",
        ".lock", ".css", ".html",
    }

    for directory in directories:
        base = ROOT / directory
        if not base.is_dir():
            continue

        for current, folders, files in os.walk(base, followlinks=False):
            folders[:] = sorted(
                name for name in folders
                if name not in excluded
                and not name.endswith(".egg-info")
            )

            for name in sorted(files):
                path = Path(current) / name

                if path.suffix not in extensions:
                    continue
                if path.is_symlink():
                    raise RuntimeError(
                        f"Source symlinks require review: {path}"
                    )
                if path.stat().st_size > MAX_FILE_BYTES:
                    raise RuntimeError(
                        f"Source file exceeds fingerprint limit: {path}"
                    )

                digest.update(
                    path.relative_to(ROOT).as_posix().encode()
                )
                digest.update(b"\0")
                digest.update(path.read_bytes())
                digest.update(b"\0")

    return digest.hexdigest()


class JobCancelled(Exception):
    pass


def stop_process(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def run_command(job_id, stage, arguments, timeout=900):
    if cancelled(job_id):
        raise JobCancelled()

    directory = job_dir(job_id)
    directory.mkdir(parents=True, exist_ok=True)

    log_path = directory / f"{stage}.log"
    started = time.monotonic()

    environment = dict(os.environ)
    environment.update({
        "LANGSMITH_TRACING": "false",
        "LANGCHAIN_TRACING_V2": "false",
        "PYTHONUNBUFFERED": "1",
        "RESEARCH_REPO_ROOT": str(ROOT),
    })

    event(
        job_id,
        stage,
        "running",
        {"argv": arguments},
    )

    with log_path.open("wb") as output:
        process = subprocess.Popen(
            arguments,
            cwd=ROOT,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            shell=False,
            start_new_session=True,
        )

        try:
            while process.poll() is None:
                heartbeat()

                if cancelled(job_id):
                    raise JobCancelled()

                if time.monotonic() - started > timeout:
                    raise RuntimeError(
                        f"{stage} exceeded its {timeout}s timeout."
                    )

                if log_path.stat().st_size > MAX_FILE_BYTES:
                    raise RuntimeError(
                        f"{stage} exceeded the log-size limit."
                    )

                time.sleep(0.5)

            return_code = process.wait()

        except BaseException:
            stop_process(process)
            raise

        finally:
            # Reap any descendants still in this command's process group.
            stop_process(process)

    detail = {
        "return_code": return_code,
        "duration_seconds": round(time.monotonic() - started, 3),
        "log": log_path.name,
    }

    event(
        job_id,
        stage,
        "passed" if return_code == 0 else "failed",
        detail,
    )

    if return_code != 0:
        raise RuntimeError(
            f"{stage} exited with code {return_code}; inspect its log."
        )


def check_junit(report):
    root = ET.parse(report).getroot()
    cases = list(root.iter("testcase"))

    counts = {
        "total": len(cases),
        "failed": sum(
            case.find("failure") is not None for case in cases
        ),
        "errors": sum(
            case.find("error") is not None for case in cases
        ),
        "skipped": sum(
            case.find("skipped") is not None for case in cases
        ),
    }

    if (
        counts["total"] == 0
        or counts["failed"]
        or counts["errors"]
        or counts["skipped"]
    ):
        raise RuntimeError(
            f"Strict regression gate rejected JUnit results: {counts}"
        )

    return counts


def write_json(path, value):
    path.write_text(
        json.dumps(value, indent=2),
        encoding="utf-8",
    )


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build_evidence(job_id):
    directory = job_dir(job_id)
    entries = []
    excluded = []

    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue

        relative = path.relative_to(directory).as_posix()
        if relative == "evidence.json":
            continue

        if (
            path.is_symlink()
            or not path.resolve().is_relative_to(directory.resolve())
            or path.stat().st_size > MAX_FILE_BYTES
            or len(entries) >= 256
        ):
            excluded.append(relative)
            continue

        entries.append({
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": file_hash(path),
        })

    write_json(
        directory / "evidence.json",
        {
            "files": entries,
            "excluded": excluded,
            "meaning": (
                "File-integrity evidence only; "
                "not research acceptance or artifact-schema approval."
            ),
        },
    )


def execute_job(job):
    job_id = job["id"]
    specification = job["spec"]
    target = specification["target"]

    directory = job_dir(job_id)
    directory.mkdir(parents=True, exist_ok=True)

    fingerprint = source_fingerprint()

    write_json(
        directory / "environment.json",
        {
            "python": sys.version,
            "interpreter": sys.executable,
            "repository": str(ROOT),
            "source_sha256": fingerprint,
            "target": target,
        },
    )

    def guard():
        if cancelled(job_id):
            raise JobCancelled()
        if source_fingerprint() != fingerprint:
            raise RuntimeError(
                "Source/configuration changed during verification. "
                "Submit a new job."
            )

    python = sys.executable

    run_command(
        job_id,
        "dependency_check",
        [python, "-m", "pip", "check"],
    )
    guard()

    run_command(
        job_id,
        "environment_packages",
        [python, "-m", "pip", "freeze"],
    )
    guard()

    if target == "data_demo":
        if not (
            specification["allow_fixtures"]
            and specification["allow_local_data"]
        ):
            raise RuntimeError("Missing explicit demo permissions.")

        run_command(
            job_id,
            "preflight",
            [python, "-m", "trading_data.preflight"],
        )
        guard()

    suite_count = {
        "request": 1,
        "plan": 2,
        "tests": 3,
        "data_demo": 3,
    }[target]

    test_results = {}

    for stage, suite in SUITES[:suite_count]:
        if not (ROOT / suite).is_dir():
            raise RuntimeError(f"Required test directory missing: {suite}")

        report = directory / f"{stage}.xml"

        run_command(
            job_id,
            stage,
            [
                python, "-m", "pytest", suite, "-v",
                "--junitxml", str(report),
                "-o", "junit_family=xunit2",
            ],
        )

        test_results[stage] = check_junit(report)
        event(job_id, stage, "gate_passed", test_results[stage])
        guard()

    if target in {"request", "plan"}:
        arguments = [
            python,
            "-m",
            "control_center.control",
            "bridge",
            target,
            "--request",
            specification["request_path"],
            "--output",
            str(directory / "state.json"),
        ]

        if specification["allow_fixtures"]:
            arguments.append("--allow-fixtures")

        run_command(job_id, target, arguments)
        guard()

    elif target == "data_demo":
        demo_root = directory / "demo"

        run_command(
            job_id,
            "seed_demo",
            [
                python, "-m", "trading_data.seed_demo",
                "--root", str(demo_root),
            ],
        )
        guard()

        run_command(
            job_id,
            "data_agent",
            [
                python, "-m", "trading_data",
                "requests/valid.json",
                "--root", str(demo_root),
                "--allow-fixtures",
                "--allow-local-data",
            ],
        )
        guard()

    outcome = {
        "operation": target,
        "tests": test_results,
        "research_acceptance": "not_evaluated",
        "data_readiness": (
            "CLI completed; not independently schema-verified by this UI"
            if target == "data_demo"
            else "not_evaluated"
        ),
    }

    write_json(directory / "outcome.json", outcome)
    return outcome


def worker():
    initialize()

    lock = (state_dir() / "worker.lock").open("a")
    try:
        fcntl.flock(
            lock.fileno(),
            fcntl.LOCK_EX | fcntl.LOCK_NB,
        )
    except BlockingIOError:
        raise SystemExit("Another worker already owns this workspace.")

    with database() as db:
        db.execute(
            """
            UPDATE jobs
            SET status='interrupted', updated=?,
                result=?
            WHERE status='running'
            """,
            (
                time.time(),
                json.dumps({
                    "error": (
                        "Previous worker stopped. "
                        "No automatic replay was attempted."
                    )
                }),
            ),
        )

    print(f"Worker ready: {ROOT}", flush=True)

    while True:
        heartbeat()

        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """
                SELECT id FROM jobs
                WHERE status='queued' AND cancel=0
                ORDER BY created
                LIMIT 1
                """
            ).fetchone()

            if row:
                db.execute(
                    """
                    UPDATE jobs
                    SET status='running', updated=?
                    WHERE id=?
                    """,
                    (time.time(), row["id"]),
                )

        if row is None:
            time.sleep(1)
            continue

        job_id = row["id"]
        job_dir(job_id).mkdir(parents=True, exist_ok=True)
        event(job_id, "job", "running")

        status = "interrupted"
        result = {}
        shutdown = False

        try:
            result = execute_job(get_job(job_id))
            status = "cancelled" if cancelled(job_id) else "succeeded"

        except JobCancelled:
            status = "cancelled"
            result = {"error": "Cancellation acknowledged by worker."}

        except KeyboardInterrupt:
            result = {"error": "Worker stopped by operator."}
            shutdown = True

        except Exception as error:
            status = "failed"
            result = {"error": str(error)}

        finally:
            try:
                build_evidence(job_id)
            except Exception as error:
                status = "failed"
                result["evidence_error"] = str(error)

            with database() as db:
                db.execute(
                    """
                    UPDATE jobs
                    SET status=?, result=?, updated=?
                    WHERE id=?
                    """,
                    (
                        status,
                        json.dumps(result),
                        time.time(),
                        job_id,
                    ),
                )

            event(job_id, "job", status, result)

        if shutdown:
            return


def bridge(mode, request_path, output, allow_fixtures):
    if request_path not in request_choices():
        raise RuntimeError("Request is outside the approved catalog.")

    from trading_request.intake import accept_request

    relative_request = Path(request_path).relative_to("request_phase")

    accepted = accept_request(
        relative_request.as_posix(),
        root=ROOT / "request_phase",
        allow_fixtures=allow_fixtures,
    )

    if accepted["status"] != "request_validated":
        raise RuntimeError("Intake did not return request_validated.")

    result = accepted

    if mode == "plan":
        from langgraph.graph import START, END, StateGraph
        from trading_supervisor.contracts import (
            SupervisorState,
            state_from_intake,
        )
        from trading_supervisor.supervisor import strategy_supervisor

        queued = state_from_intake(
            accepted,
            allow_fixtures=allow_fixtures,
        )

        builder = StateGraph(SupervisorState)
        builder.add_node(
            "strategy_supervisor",
            strategy_supervisor,
        )
        builder.add_edge(START, "strategy_supervisor")
        builder.add_edge("strategy_supervisor", END)

        result = builder.compile().invoke(
            queued,
            config={"recursion_limit": 10},
        )

        if (
            result["status"] != "planned"
            or result["iteration"] != 0
            or result["execution_authorized"] is not False
        ):
            raise RuntimeError(
                "Supervisor violated the plan-only boundary."
            )

    write_json(Path(output), result)
    print(json.dumps({"status": result["status"]}))


def create_app():
    initialize()
    app = FastAPI(title="Research Control API", version="0.1.0")

    @app.middleware("http")
    async def protect(request: Request, call_next):
        if request.url.hostname not in {
            "localhost", "127.0.0.1", "testserver"
        }:
            return JSONResponse(
                {"detail": "Untrusted host"},
                status_code=400,
            )

        if (
            request.method not in {"GET", "HEAD"}
            and request.headers.get("origin")
        ):
            return JSONResponse(
                {"detail": "Browser-origin mutations are disabled"},
                status_code=403,
            )

        expected = (
            state_dir() / "api-token"
        ).read_text().strip()

        actual = request.headers.get("authorization", "")

        if not hmac.compare_digest(
            actual,
            f"Bearer {expected}",
        ):
            return JSONResponse(
                {"detail": "Unauthorized"},
                status_code=401,
            )

        return await call_next(request)

    def required_job(job_id):
        try:
            return get_job(job_id)
        except (KeyError, ValueError):
            raise HTTPException(404, "Job not found")

    @app.get("/health")
    def health():
        with database() as db:
            row = db.execute(
                """
                SELECT value FROM metadata
                WHERE key='worker_heartbeat'
                """
            ).fetchone()

        online = (
            row is not None
            and time.time() - float(row["value"]) < 10
        )

        return {
            "api": "ready",
            "worker_online": online,
            "root": str(ROOT),
            "python": sys.version.split()[0],
        }

    @app.get("/catalog")
    def catalog():
        return {
            "requests": request_choices(),
            "targets": ["tests", "request", "plan", "data_demo"],
        }

    @app.post("/jobs", status_code=202)
    def create_job(specification: Submission):
        return submit(specification)

    @app.get("/jobs")
    def jobs():
        with database() as db:
            rows = db.execute(
                """
                SELECT id FROM jobs
                ORDER BY created DESC
                LIMIT 100
                """
            ).fetchall()
        return [get_job(row["id"]) for row in rows]

    @app.get("/jobs/{job_id}")
    def job(job_id: str):
        return required_job(job_id)

    @app.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        required_job(job_id)

        with database() as db:
            db.execute(
                """
                UPDATE jobs
                SET cancel=1,
                    status=CASE
                        WHEN status='queued' THEN 'cancelled'
                        ELSE status
                    END,
                    updated=?
                WHERE id=?
                  AND status IN ('queued', 'running')
                """,
                (time.time(), job_id),
            )

        return get_job(job_id)

    @app.get("/jobs/{job_id}/events")
    def events(job_id: str):
        required_job(job_id)

        with database() as db:
            rows = db.execute(
                """
                SELECT * FROM events
                WHERE job_id=?
                ORDER BY id
                """,
                (job_id,),
            ).fetchall()

        result = []
        for row in rows:
            item = dict(row)
            item["detail"] = json.loads(item["detail"])
            result.append(item)
        return result

    @app.get("/jobs/{job_id}/files")
    def files(job_id: str):
        required_job(job_id)
        directory = job_dir(job_id)
        evidence = directory / "evidence.json"

        if evidence.is_file():
            content = json.loads(evidence.read_text())
            return content["files"] + [{
                "path": "evidence.json",
                "bytes": evidence.stat().st_size,
                "sha256": None,
            }]

        return [
            {
                "path": path.relative_to(directory).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": None,
            }
            for path in sorted(directory.glob("*"))
            if path.is_file() and not path.is_symlink()
        ]

    def required_file(job_id, name):
        required_job(job_id)
        directory = job_dir(job_id).resolve()
        path = directory / name

        if (
            not path.is_file()
            or path.is_symlink()
            or not path.resolve().is_relative_to(directory)
        ):
            raise HTTPException(404, "File not found")

        if path.stat().st_size > MAX_FILE_BYTES:
            raise HTTPException(413, "File exceeds download limit")

        evidence_path = directory / "evidence.json"
        if evidence_path.exists() and name != "evidence.json":
            manifest = json.loads(evidence_path.read_text())
            match = next(
                (
                    entry for entry in manifest["files"]
                    if entry["path"] == name
                ),
                None,
            )

            if match is None:
                raise HTTPException(404, "File is outside evidence index")

            if file_hash(path) != match["sha256"]:
                raise HTTPException(409, "Evidence hash mismatch")

        return path

    @app.get("/jobs/{job_id}/file/{name:path}")
    def download(job_id: str, name: str):
        path = required_file(job_id, name)
        return FileResponse(
            path,
            filename=path.name,
            media_type="application/octet-stream",
        )

    @app.get("/jobs/{job_id}/log/{name}")
    def log(job_id: str, name: str):
        if not re.fullmatch(r"[a-z0-9_]+\.log", name):
            raise HTTPException(404, "Log not found")

        path = required_file(job_id, name)
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 32768))
            text = stream.read().decode("utf-8", errors="replace")

        return {"text": text}

    return app


def main():
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("init")
    subcommands.add_parser("api")
    subcommands.add_parser("worker")

    bridge_parser = subcommands.add_parser("bridge")
    bridge_parser.add_argument("mode", choices=["request", "plan"])
    bridge_parser.add_argument("--request", required=True)
    bridge_parser.add_argument("--output", required=True)
    bridge_parser.add_argument("--allow-fixtures", action="store_true")

    arguments = parser.parse_args()

    if arguments.command == "init":
        initialize()
        print(f"Initialized control workspace: {state_dir()}")

    elif arguments.command == "api":
        import uvicorn

        uvicorn.run(
            create_app(),
            host="127.0.0.1",
            port=8000,
        )

    elif arguments.command == "worker":
        worker()

    elif arguments.command == "bridge":
        bridge(
            arguments.mode,
            arguments.request,
            arguments.output,
            arguments.allow_fixtures,
        )


if __name__ == "__main__":
    main()
```

### What this implements

- SQLite-backed jobs and event history
- One worker per workspace
- Fixed operation registry—no arbitrary shell commands from the UI
- Dependency checks and phase-specific test gates
- JUnit-based test decisions
- Cancellation, timeouts, and bounded logs
- Source/configuration fingerprint checks between stages
- Request and supervisor integration using the interfaces already discussed
- Data demo execution using your existing CLI
- Downloadable evidence with SHA-256 checks

**Strict gate policy:** skipped tests and zero-test runs block execution. If your existing suites intentionally skip tests, review that policy before relaxing it.

# 4. Add the Streamlit interface

Create **`control_center/ui.py`**:

```python
import os
import uuid

from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import httpx
import streamlit as st


ROOT = Path(
    os.environ.get("RESEARCH_REPO_ROOT", os.getcwd())
).resolve()

API = "http://127.0.0.1:8000"
TOKEN_PATH = ROOT / ".research-control/api-token"

st.set_page_config(
    page_title="Research Control Center",
    page_icon=":material/account_tree:",
    layout="wide",
)

st.markdown(
    """
    <style>
    :root {
        --cc-accent: #01696f;
        --cc-space: 1rem;
        --cc-text-sm: clamp(.875rem, .85rem + .1vw, 1rem);
        --cc-title: clamp(1.5rem, 1.3rem + .6vw, 2rem);
    }
    .block-container {
        max-width: 1440px;
        padding-top: 2rem;
    }
    h1 {
        font-size: var(--cc-title) !important;
        letter-spacing: -.035em;
    }
    [data-testid="stMetricValue"] {
        font-variant-numeric: tabular-nums;
    }
    button[kind="primary"] {
        background: var(--cc-accent);
        border-color: var(--cc-accent);
    }
    button {
        min-height: 44px;
    }
    .cc-eyebrow {
        font-size: var(--cc-text-sm);
        letter-spacing: .1em;
        text-transform: uppercase;
        opacity: .7;
        margin-bottom: .5rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="cc-eyebrow">Local workspace / execution evidence</div>',
    unsafe_allow_html=True,
)

st.title("Research Control Center")
st.caption(
    "Verify the implementation. Run a bounded operation. "
    "Keep the evidence."
)

if not TOKEN_PATH.is_file():
    st.error(
        "Workspace is not initialized. Run: "
        "python -m control_center.control init"
    )
    st.stop()


def api(method, path, **kwargs):
    token = TOKEN_PATH.read_text().strip()

    response = httpx.request(
        method,
        API + path,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
        **kwargs,
    )
    response.raise_for_status()
    return response


try:
    health = api("GET", "/health").json()
    catalog = api("GET", "/catalog").json()
except (httpx.HTTPError, OSError) as error:
    st.error(
        "The control API is unavailable. Start the API process, "
        "then refresh this page."
    )
    with st.expander("Connection details"):
        st.code(str(error))
    st.stop()


with st.sidebar:
    st.markdown("### Workspace")
    st.code(health["root"], language=None)
    st.caption(f"Python {health['python']}")
    st.caption("API: ready")

    if health["worker_online"]:
        st.success("Worker connected")
    else:
        st.warning("Worker not connected")

    st.divider()
    st.markdown("### Boundaries")
    st.caption(
        "Local requests and fixture-based data demo only. "
        "No live trading. No arbitrary command input."
    )
    st.caption(
        "Use Streamlit Settings → Theme for light/dark appearance."
    )


page = st.radio(
    "Navigation",
    ["Workspace", "Tests", "Runs", "Artifacts", "Settings"],
    horizontal=True,
    label_visibility="collapsed",
)


def submit_job(payload):
    payload["submission_id"] = uuid.uuid4().hex

    try:
        result = api("POST", "/jobs", json=payload).json()
    except httpx.HTTPStatusError as error:
        try:
            detail = error.response.json()
        except ValueError:
            detail = error.response.text
        st.error(f"Submission rejected: {detail}")
        return
    except httpx.HTTPError as error:
        st.error(
            "Submission response was not received. Check Runs "
            "before submitting again."
        )
        st.code(str(error))
        return

    st.session_state["selected_job"] = result["id"]
    st.success(
        f"Queued job {result['id'][:12]}. "
        "Open Runs to watch execution."
    )


if page == "Workspace":
    st.subheader("Verify & run")

    labels = {
        "Validate request": "request",
        "Plan only": "plan",
        "Prepare isolated data demo": "data_demo",
    }

    operation = st.selectbox("Operation", list(labels))
    target = labels[operation]

    if target == "request":
        st.info(
            "Gate: Phase 1 tests. "
            "Expected operation result: request_validated."
        )
    elif target == "plan":
        st.info(
            "Gates: Phase 1 and Phase 2 tests. "
            "Expected operation result: planned; "
            "execution remains unauthorized."
        )
    else:
        st.warning(
            "Gates: preflight and all three regression suites. "
            "The worker seeds an isolated demo directory. "
            "This does not process a selected production snapshot."
        )

    with st.form("run_request"):
        request_path = ""

        if target in {"request", "plan"}:
            if catalog["requests"]:
                request_path = st.selectbox(
                    "Request",
                    catalog["requests"],
                )
            else:
                st.warning(
                    "No request JSON files were found in "
                    "request_phase/examples/requests/."
                )

        allow_fixtures = st.checkbox(
            "Allow explicitly marked test fixtures",
            value=False,
        )

        allow_local_data = False
        if target == "data_demo":
            allow_local_data = st.checkbox(
                "Allow the Data Agent to read local demo data",
                value=False,
            )

        submitted = st.form_submit_button(
            "Verify & run",
            type="primary",
            disabled=(
                not health["worker_online"]
                or (
                    target in {"request", "plan"}
                    and not catalog["requests"]
                )
            ),
        )

    if submitted:
        submit_job({
            "target": target,
            "request_path": request_path,
            "allow_fixtures": allow_fixtures,
            "allow_local_data": allow_local_data,
        })

    st.divider()
    st.subheader("Available pipeline")

    st.code(
        "Request → Supervisor → Data demo\n"
        "Regime → Signal → Calibration → Backtest → Diagnostics\n"
        "         not connected in this MVP",
        language=None,
    )


elif page == "Tests":
    st.subheader("Regression verification")

    st.write(
        "Run dependency checks followed by Phase 1, Phase 2, "
        "and Phase 3 tests. This operation does not run agents."
    )

    st.table([
        {"Gate": "Phase 1", "Suite": "request_phase/tests"},
        {"Gate": "Phase 2", "Suite": "supervisor_phase/tests"},
        {"Gate": "Phase 3", "Suite": "data_phase/tests"},
    ])

    st.caption(
        "Policy: nonzero exit codes, missing reports, zero tests, "
        "failures, errors, and skipped tests block the operation."
    )

    if st.button(
        "Run regression tests",
        type="primary",
        disabled=not health["worker_online"],
    ):
        submit_job({"target": "tests"})


elif page in {"Runs", "Artifacts"}:
    @st.fragment(run_every="3s")
    def monitor():
        try:
            jobs = api("GET", "/jobs").json()
        except httpx.HTTPError as error:
            st.error(f"Could not refresh jobs: {error}")
            return

        if not jobs:
            st.info(
                "Your execution history will appear here. "
                "Start with Tests → Run regression tests."
            )
            return

        rows = [
            {
                "Job": job["id"][:12],
                "Operation": job["spec"]["target"],
                "Status": job["status"],
                "Created": datetime.fromtimestamp(
                    job["created"]
                ).strftime("%Y-%m-%d %H:%M:%S"),
                "Cancellation requested": job["cancel"],
            }
            for job in jobs
        ]

        st.dataframe(
            rows,
            use_container_width=True,
            hide_index=True,
        )

        identifiers = [job["id"] for job in jobs]
        preferred = st.session_state.get(
            "selected_job",
            identifiers[0],
        )

        selected = st.selectbox(
            "Inspect job",
            identifiers,
            index=(
                identifiers.index(preferred)
                if preferred in identifiers
                else 0
            ),
            format_func=lambda value: value[:12],
            key="job_inspector",
        )

        job = next(
            item for item in jobs if item["id"] == selected
        )

        st.caption(f"Full job ID: {selected}")

        status_column, operation_column, acceptance_column = (
            st.columns(3)
        )
        status_column.metric("Job status", job["status"])
        operation_column.metric(
            "Operation",
            job["spec"]["target"],
        )
        acceptance_column.metric(
            "Research acceptance",
            "Not evaluated",
        )

        if job["status"] in {"queued", "running"}:
            if st.button(
                "Request cancellation",
                key=f"cancel_{selected}",
                disabled=job["cancel"],
            ):
                api("POST", f"/jobs/{selected}/cancel")
                st.info(
                    "Cancellation requested. "
                    "Wait for worker acknowledgement."
                )

        if job["result"].get("error"):
            st.error(job["result"]["error"])

        events = api(
            "GET",
            f"/jobs/{selected}/events",
        ).json()

        files = api(
            "GET",
            f"/jobs/{selected}/files",
        ).json()

        overview_tab, tests_tab, logs_tab, files_tab = st.tabs(
            ["Overview", "Tests", "Logs", "Evidence"]
        )

        with overview_tab:
            st.json({
                "submission": job["spec"],
                "result": job["result"],
            })

            st.dataframe(
                [
                    {
                        "Stage": item["stage"],
                        "Status": item["status"],
                        "Detail": str(item["detail"]),
                    }
                    for item in events
                ],
                use_container_width=True,
                hide_index=True,
            )

        with tests_tab:
            gates = [
                {
                    "Stage": item["stage"],
                    **item["detail"],
                }
                for item in events
                if item["status"] == "gate_passed"
            ]

            if gates:
                st.dataframe(
                    gates,
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info(
                    "No regression gate has passed yet. "
                    "Check Logs for running or rejected stages."
                )

        with logs_tab:
            logs = [
                item["path"] for item in files
                if (
                    item["path"].endswith(".log")
                    and "/" not in item["path"]
                )
            ]

            if logs:
                selected_log = st.selectbox(
                    "Command log",
                    logs,
                    key=f"log_{selected}",
                )

                response = api(
                    "GET",
                    f"/jobs/{selected}/log/{selected_log}",
                ).json()

                st.caption("Showing the last 32 KiB.")
                st.code(response["text"], language="text")
            else:
                st.info(
                    "Logs appear when the worker starts a command."
                )

        with files_tab:
            st.caption(
                "Hashes verify captured bytes, not research quality. "
                "Oversized files are excluded from evidence downloads."
            )

            if files:
                st.dataframe(
                    files,
                    use_container_width=True,
                    hide_index=True,
                )

                name = st.selectbox(
                    "Evidence file",
                    [item["path"] for item in files],
                    key=f"file_{selected}",
                )

                if st.button(
                    "Load selected file",
                    key=f"load_{selected}",
                ):
                    response = api(
                        "GET",
                        f"/jobs/{selected}/file/"
                        + quote(name, safe="/"),
                    )

                    st.download_button(
                        "Download evidence",
                        data=response.content,
                        file_name=Path(name).name,
                        mime="application/octet-stream",
                        key=f"download_{selected}",
                    )
            else:
                st.info("No evidence files have been created yet.")

    monitor()


elif page == "Settings":
    st.subheader("Workspace settings")

    st.json({
        "repository": health["root"],
        "api": API,
        "python": health["python"],
        "worker_connected": health["worker_online"],
        "request_catalog": (
            "request_phase/examples/requests/*.json"
        ),
        "execution_mode": "local / trusted repository",
    })

    st.warning(
        "This MVP is not a remote or multi-user service. "
        "Keep both servers bound to 127.0.0.1. "
        "Do not execute untrusted repositories or pull requests."
    )

    st.markdown(
        """
        **Not implemented yet**
        
        - Live-data authorization
        - Independent Data Agent artifact-schema verification
        - LangGraph checkpoint/resume controls
        - Remote authentication and role-based access
        - GitHub Actions synchronization
        - Regime, signal, calibration, and backtest interfaces
        """
    )
```

The interface uses forms for deliberate submission rather than executing an operation on every field change—the form interaction pattern described in the [Streamlit forms documentation](https://docs.streamlit.io/develop/concepts/architecture/forms).

# 5. Add control-plane tests

Create **`control_center/tests/test_control.py`**:

```python
import uuid

import pytest

from fastapi.testclient import TestClient

from control_center import control


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "ROOT", tmp_path)

    application = control.create_app()
    token = (
        tmp_path / ".research-control/api-token"
    ).read_text().strip()

    with TestClient(application) as test_client:
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client


def test_requires_authentication(client):
    client.headers.pop("Authorization")

    response = client.get("/health")

    assert response.status_code == 401


def test_health_reports_no_worker_initially(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["worker_online"] is False


def test_tests_job_can_be_queued(client):
    response = client.post(
        "/jobs",
        json={"target": "tests"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"


def test_duplicate_submission_is_idempotent(client):
    submission_id = uuid.uuid4().hex
    payload = {
        "submission_id": submission_id,
        "target": "tests",
    }

    first = client.post("/jobs", json=payload)
    second = client.post("/jobs", json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert len(client.get("/jobs").json()) == 1


def test_reusing_id_with_different_payload_is_rejected(client):
    submission_id = uuid.uuid4().hex

    client.post(
        "/jobs",
        json={
            "submission_id": submission_id,
            "target": "tests",
        },
    )

    response = client.post(
        "/jobs",
        json={
            "submission_id": submission_id,
            "target": "data_demo",
            "allow_fixtures": True,
            "allow_local_data": True,
        },
    )

    assert response.status_code == 409


def test_arbitrary_operation_is_rejected(client):
    response = client.post(
        "/jobs",
        json={"target": "shell"},
    )

    assert response.status_code == 422


def test_unknown_fields_are_rejected(client):
    response = client.post(
        "/jobs",
        json={
            "target": "tests",
            "command": "echo unwanted",
        },
    )

    assert response.status_code == 422


def test_data_demo_requires_both_permissions(client):
    response = client.post(
        "/jobs",
        json={
            "target": "data_demo",
            "allow_fixtures": True,
        },
    )

    assert response.status_code == 422


def test_request_outside_catalog_is_rejected(client):
    response = client.post(
        "/jobs",
        json={
            "target": "request",
            "request_path": "/etc/passwd",
        },
    )

    assert response.status_code == 422


def test_queued_job_can_be_cancelled(client):
    job = client.post(
        "/jobs",
        json={"target": "tests"},
    ).json()

    response = client.post(
        f"/jobs/{job['id']}/cancel"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["cancel"] is True


def test_unknown_job_returns_404(client):
    response = client.get(f"/jobs/{uuid.uuid4().hex}")

    assert response.status_code == 404


def test_browser_origin_mutation_is_rejected(client):
    response = client.post(
        "/jobs",
        json={"target": "tests"},
        headers={"Origin": "https://untrusted.example"},
    )

    assert response.status_code == 403


def test_junit_with_passing_test_is_accepted(tmp_path):
    report = tmp_path / "report.xml"
    report.write_text(
        '<testsuite><testcase name="ok"/></testsuite>'
    )

    counts = control.check_junit(report)

    assert counts["total"] == 1
    assert counts["failed"] == 0


def test_junit_with_skipped_test_is_rejected(tmp_path):
    report = tmp_path / "report.xml"
    report.write_text(
        '<testsuite><testcase name="skip">'
        '<skipped/></testcase></testsuite>'
    )

    with pytest.raises(RuntimeError):
        control.check_junit(report)


def test_empty_junit_is_rejected(tmp_path):
    report = tmp_path / "report.xml"
    report.write_text("<testsuite/>")

    with pytest.raises(RuntimeError):
        control.check_junit(report)
```

These tests exercise the control plane. They do **not** replace your phase tests or prove compatibility with your actual Data Agent implementation.

# 6. Install in a separate environment

Run each command separately:

```bash
cd ~/trading-research-graph

python3.12 -m venv control_center/.venv

source control_center/.venv/bin/activate
```

Install your existing tested dependencies together with the new UI requirements:

```bash
python -m pip install \
  -r data_phase/requirements-tested.txt \
  -r control_center/requirements.txt
```

Then install your three local packages:

```bash
python -m pip install \
  -e './request_phase[dev]' \
  -e './supervisor_phase[dev]' \
  -e './data_phase[dev]'
```

Check compatibility:

```bash
python -m pip check
```

**Stop if the resolver or dependency check reports conflicts.** Do not use `--no-deps` to force installation.

Add these entries to your existing `.gitignore`, without replacing its current contents:

```gitignore
.research-control/
control_center/.venv/
```

# 7. Test before starting services

Run the new tests:

```bash
python -m pytest control_center/tests -v
```

Then verify the existing phases in the **same environment** that will run the worker:

```bash
python -m pytest request_phase/tests -v
```

```bash
python -m pytest supervisor_phase/tests -v
```

```bash
python -m pytest data_phase/tests -v
```

Only continue after these pass.

# 8. Start the three processes

Use **three VS Code terminals**. Each terminal should start from the repository root and activate the same environment.

### Terminal 1 — Control API

```bash
cd ~/trading-research-graph
source control_center/.venv/bin/activate

python -m control_center.control init
python -m control_center.control api
```

Expected listening address:

```text
http://127.0.0.1:8000
```

### Terminal 2 — Worker

```bash
cd ~/trading-research-graph
source control_center/.venv/bin/activate

python -m control_center.control worker
```

Expected message:

```text
Worker ready: /home/leekwan/trading-research-graph
```

### Terminal 3 — Streamlit

```bash
cd ~/trading-research-graph
source control_center/.venv/bin/activate

python -m streamlit run control_center/ui.py \
  --server.address 127.0.0.1 \
  --server.port 8501 \
  --browser.gatherUsageStats false
```

Open:

```text
http://localhost:8501
```

# 9. Verify the UI incrementally

Do not begin with the Data Agent. Use this sequence:

| Order | UI action | Expected outcome |
|---|---|---|
| 1 | Open **Settings** | Correct repository, Python version, and connected worker |
| 2 | **Tests → Run regression tests** | Phase 1–3 JUnit evidence and a succeeded job |
| 3 | **Workspace → Validate request** | Downloadable `state.json` with `request_validated` |
| 4 | **Workspace → Plan only** | `planned`, iteration `0`, execution unauthorized |
| 5 | **Workspace → Prepare isolated data demo** | Preflight, three suites, seeding, then Data Agent CLI |
| 6 | Open **Runs → Evidence** | Logs, XML reports, environment, outcome, hashes |

For the existing example request, enable **Allow explicitly marked test fixtures** when required by your intake contract.

For the data demo, both permission checkboxes must be enabled.

### Check the failure path

Submit a regression job and request cancellation while it is queued or running.

Expected behavior:

```text
Cancellation requested
         ↓
Worker stops the active command
         ↓
Job status becomes cancelled
```

A cancellation request is **not** shown as completed until the worker acknowledges it.

# 10. Know the MVP boundaries

**A green job means the selected operation completed—not that a strategy is profitable, robust, or approved.**

There are also three important implementation limits:

- **Data integration:** the existing `trading_data` CLI is invoked without inventing internal interfaces. A zero exit code is recorded, but the UI does not independently certify `data_ready` or validate your Data Agent’s artifact schema.
- **Crash recovery:** persisted jobs survive UI/API restarts. Jobs interrupted by worker loss are marked `interrupted`, not automatically replayed. After an abrupt worker kill or machine failure, inspect for surviving child processes before restarting execution.
- **Security:** this is for a trusted local repository. A token and fixed commands reduce accidental misuse, but pytest and agent code still execute with your operating-system permissions; this is **not a sandbox**.

**First checkpoint:** get the control-plane tests passing, start the three processes, and successfully run **Tests Only** from the browser before enabling the request, supervisor, and data-demo operations.
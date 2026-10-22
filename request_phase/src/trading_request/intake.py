from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

Text = Annotated[StrictStr, Field(min_length=1)]
Identifier = Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResearchRequest(Contract):
    schema_version: Literal["1"] = "1"
    request_id: Identifier
    strategy_spec_uri: Text
    dataset_snapshot_id: Identifier
    universe: Annotated[list[Text], Field(min_length=1)]
    start: date
    end: date
    max_iterations: Annotated[StrictInt, Field(ge=1, le=20)] = 3

    @model_validator(mode="after")
    def check_consistency(self) -> ResearchRequest:
        if self.start >= self.end:
            raise ValueError("start must be before end (inclusive date window)")
        if len(set(self.universe)) != len(self.universe):
            raise ValueError("universe must not contain duplicate instruments")
        return self


class StrategySpec(Contract):
    schema_version: Literal["1"]
    strategy_id: Identifier
    bar_frequency: Text
    research_question: Text


class SnapshotManifest(Contract):
    schema_version: Literal["1"]
    snapshot_id: Identifier
    fixture_only: bool = False
    instruments: Annotated[list[Text], Field(min_length=1)]
    available_start: date
    available_end: date

    @model_validator(mode="after")
    def check_dates(self) -> SnapshotManifest:
        if self.available_start > self.available_end:
            raise ValueError("manifest date range is reversed")
        return self


def confined(root: Path, value: str) -> Path:
    root = root.resolve(strict=True)
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError("use a project-relative path, not an absolute path or URI")
    candidate = (root / candidate).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("path escapes project root")
    if not candidate.is_file():
        raise FileNotFoundError(f"file not found: {candidate}")
    return candidate


def accept_request(
    request_path: str,
    *,
    root: Path,
    allow_fixtures: bool = False,
) -> dict:
    root = root.resolve(strict=True)
    request = ResearchRequest.model_validate_json(
        confined(root, request_path).read_bytes()
    )
    spec_path = confined(root, request.strategy_spec_uri)
    spec_bytes = spec_path.read_bytes()
    spec = StrategySpec.model_validate_json(spec_bytes)
    manifest_path = confined(
        root, f"data/manifests/{request.dataset_snapshot_id}.json"
    )
    manifest_bytes = manifest_path.read_bytes()
    manifest = SnapshotManifest.model_validate_json(manifest_bytes)
    if manifest.snapshot_id != request.dataset_snapshot_id:
        raise ValueError("snapshot ID does not match manifest")
    if manifest.fixture_only and not allow_fixtures:
        raise ValueError("fixture snapshot rejected; use --allow-fixtures for smoke tests only")
    missing = set(request.universe) - set(manifest.instruments)
    if missing:
        raise ValueError(f"instruments not in snapshot: {sorted(missing)}")
    if request.start < manifest.available_start or request.end > manifest.available_end:
        raise ValueError("requested dates exceed snapshot coverage")

    normalized = request.model_dump(mode="json")
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return {
        "status": "request_validated",
        "validation_scope": "metadata_only",
        "fixture_only": manifest.fixture_only,
        "request": normalized,
        "request_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "strategy_spec_sha256": hashlib.sha256(spec_bytes).hexdigest(),
        "snapshot_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "strategy_id": spec.strategy_id,
        "initial_state": {**normalized, "status": "queued", "iteration": 0, "events": []},
    }

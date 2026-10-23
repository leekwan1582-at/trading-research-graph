from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator
from trading_supervisor.contracts import SupervisorState

SHA = Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
Text = Annotated[str, Field(min_length=1)]


class DataContract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class AcceptedRequest(DataContract):
    schema_version: Literal['1']
    request_id: Text
    strategy_spec_uri: Text
    dataset_snapshot_id: Annotated[str, Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')]
    universe: Annotated[list[Text], Field(min_length=1)]
    start: date
    end: date
    max_iterations: Annotated[StrictInt, Field(ge=1, le=20)]

    @model_validator(mode='after')
    def consistent(self):
        if self.start >= self.end:
            raise ValueError('start must precede end for this contract')
        if len(self.universe) != len(set(self.universe)):
            raise ValueError('duplicate universe instruments')
        return self


class CatalogEntry(DataContract):
    schema_version: Literal['1']
    snapshot_id: Annotated[str, Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')]
    parquet_path: Text
    parquet_sha256: SHA
    intake_manifest_sha256: SHA
    fixture_only: StrictBool
    instruments: Annotated[list[Text], Field(min_length=1)]
    interval_seconds: Annotated[StrictInt, Field(ge=1, le=86400)]
    timestamp_convention: Literal['bar_open_utc']
    calendar_policy: Literal['continuous_24x7', 'unchecked']
    price_policy: Literal['positive', 'allow_nonpositive']
    source_url: Text
    source_archive_sha256: SHA
    provenance_note: Text


@dataclass(frozen=True)
class DataAccess:
    root: Path
    allow_local_data: bool = False
    allow_fixtures: bool = False
    max_input_bytes: int = 32 * 1024 * 1024
    max_input_rows: int = 2_000_000

    def __post_init__(self):
        if type(self.allow_local_data) is not bool or type(self.allow_fixtures) is not bool:
            raise ValueError('access switches must be booleans')
        for value in (self.max_input_bytes, self.max_input_rows):
            if type(value) is not int or value <= 0:
                raise ValueError('resource caps must be positive integers')


class DataState(SupervisorState, total=False):
    data_artifact: dict[str, Any]
    data_quality: dict[str, Any]

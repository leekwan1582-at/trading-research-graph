import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .storage import confined, digest, limited_read
from .validation import DataRejected


def load_prepared(root: Path, receipt_ref: dict, *, max_bytes: int = 64 * 1024 * 1024):
    """Read through the committed receipt, never by globbing runs/data directories."""
    def verified(reference):
        blob = limited_read(confined(root, reference['path']), max_bytes)
        if digest(blob) != reference['sha256'] or len(blob) != reference['bytes']:
            raise DataRejected('published artifact hash or size mismatch')
        return blob
    receipt = json.loads(verified(receipt_ref))
    bars = pq.ParquetFile(pa.BufferReader(verified(receipt['bars']))).read()
    quality = json.loads(verified(receipt['quality']))
    if bars.num_rows != receipt['rows'] or quality['selected_rows'] != receipt['rows']:
        raise DataRejected('published artifact row counts disagree')
    return bars, quality, receipt

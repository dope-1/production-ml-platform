"""Chunked, vectorized CSV scoring with an atomic output publication."""

import csv
import os
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pandas as pd
from sqlalchemy.engine import Engine

from ml_platform.data.validation import FEATURES, ID
from ml_platform.inference.schema import validate_features
from ml_platform.inference.service import Snapshot
from ml_platform.inference.storage import log_predictions


def score_csv(
    source: Path,
    destination: Path,
    snapshot: Snapshot,
    engine: Engine,
    model_name: str,
    cohort: str = "live",
    chunk_size: int = 2000,
    *,
    max_bytes: int = 64 * 1024 * 1024,
    max_rows: int = 100_000,
) -> dict[str, object]:
    if source.is_symlink() or destination.is_symlink():
        raise ValueError("Batch paths must not be symbolic links")
    if not source.is_file() or (destination.exists() and not destination.is_file()):
        raise ValueError("Batch paths must be regular files")
    if max_bytes < 1 or max_rows < 1:
        raise ValueError("Batch limits must be positive")
    if source.stat().st_size > max_bytes:
        raise ValueError("Batch input exceeds the byte limit")
    if source.resolve() == destination.resolve() or (
        destination.exists() and os.path.samefile(source, destination)
    ):
        raise ValueError("Input and output paths must differ")
    if not 1 <= chunk_size <= 10_000:
        raise ValueError("Chunk size must be between 1 and 10000")
    with source.open(newline="", encoding="utf-8-sig") as stream:
        header = next(csv.reader(stream), [])
    if len(header) != len(set(header)) or set(header) != {ID, *FEATURES}:
        raise ValueError("CSV requires customer_id and exactly the 19 financial features")
    destination.parent.mkdir(parents=True, exist_ok=True)
    job_id = uuid4().hex
    temporary = destination.with_name(destination.name + "." + job_id + ".tmp")
    count = 0
    seen: set[int] = set()
    try:
        with (
            temporary.open("x", newline="", encoding="utf-8") as output_stream,
            engine.begin() as connection,
        ):
            for chunk in pd.read_csv(source, chunksize=chunk_size):
                if count + len(chunk) > max_rows:
                    raise ValueError("Batch input exceeds the row limit")
                X = validate_features(chunk[FEATURES])
                ids = chunk[ID]
                if (
                    not pd.api.types.is_integer_dtype(ids)
                    or ids.duplicated().any()
                    or not ids.between(1, 2**53 - 1).all()
                    or seen.intersection(ids.tolist())
                ):
                    raise ValueError("Invalid or duplicate customer IDs")
                seen.update(ids.tolist())
                start = perf_counter()
                p = snapshot.score(X)
                rows = log_predictions(
                    connection,
                    snapshot,
                    X,
                    p,
                    job_id,
                    model_name,
                    cohort,
                    (perf_counter() - start) * 1000 / len(X),
                )
                output = pd.DataFrame(rows).rename(columns={"timestamp": "prediction_timestamp"})
                output.insert(0, ID, ids.to_numpy())
                output.to_csv(output_stream, header=count == 0, index=False)
                count += len(X)
            if count == 0:
                raise ValueError("Empty batch")
            output_stream.flush()
            os.fsync(output_stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "job_id": job_id,
        "rows": count,
        "model_version": snapshot.version,
        "output": str(destination),
    }

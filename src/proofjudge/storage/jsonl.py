"""JSONL read/write utilities with atomic writes for crash safety."""

import logging
import os
from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


def append_jsonl(path: Path, record: BaseModel) -> None:
    """Atomically append a single record to a JSONL file.

    Uses flush + fsync to ensure the record is durably written before returning.
    A crash during this call loses at most the current record.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = record.model_dump_json() + "\n"
    with path.open("a") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def read_jsonl[T: BaseModel](path: Path, model: type[T]) -> Iterator[T]:
    """Stream records from a JSONL file, validating each against the model.

    Skips invalid records with a warning rather than failing the whole file.
    """
    if not path.exists():
        return
    with path.open() as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield model.model_validate_json(line)
            except ValidationError as e:
                logger.warning("Skipping invalid record at %s:%d: %s", path, line_num, e)


def write_json_file(path: Path, record: BaseModel) -> None:
    """Write a single record as a JSON file (not JSONL). For per-PR extraction files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = record.model_dump_json(indent=2) + "\n"
    # Write to temp file then rename for atomicity
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    tmp_path.rename(path)


def read_json_file[T: BaseModel](path: Path, model: type[T]) -> T | None:
    """Read a single JSON file into a model. Returns None if file doesn't exist."""
    if not path.exists():
        return None
    content = path.read_text()
    return model.model_validate_json(content)

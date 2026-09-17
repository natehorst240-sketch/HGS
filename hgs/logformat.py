"""Parsing of stored/downloaded log data into rows.

The real byte layout of each record is unknown until sample files are provided.
`parse()` currently supports a self-describing CSV/JSON fallback so the viewer
is runnable today with demo data, and leaves a clear seam for the binary parser.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from .logtypes import LogType


def parse(raw: bytes, log_type: LogType) -> list[list[str]]:
    """Return a list of rows (each a list of strings) for the given log type.

    Order of attempts:
      1. JSON  {"rows": [[...], ...]}
      2. CSV
      3. TODO(format): real binary record parser once the layout is known.
    """
    text = _try_text(raw)
    if text is not None:
        stripped = text.lstrip()
        if stripped.startswith("{"):
            try:
                doc = json.loads(text)
                return [[str(c) for c in row] for row in doc.get("rows", [])]
            except json.JSONDecodeError:
                pass
        # CSV fallback
        reader = csv.reader(io.StringIO(text))
        rows = [row for row in reader if row]
        # drop a header row if it matches the column names
        if rows and list(rows[0]) == list(log_type.columns):
            rows = rows[1:]
        return rows

    # TODO(format): parse fixed-width binary records here.
    # Each record likely begins with a timestamp; field widths per log type must
    # be recovered from a sample file or the disassembly.
    raise NotImplementedError(
        f"Binary parser for '{log_type.key}' not implemented yet — "
        "supply a sample data file to reverse-engineer the layout."
    )


def parse_file(path: str | Path, log_type: LogType) -> list[list[str]]:
    return parse(Path(path).read_bytes(), log_type)


def _try_text(raw: bytes) -> str | None:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("latin-1")
        except UnicodeDecodeError:
            return None

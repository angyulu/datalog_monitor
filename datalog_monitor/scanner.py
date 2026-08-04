"""Recursive CSV discovery and cached parsing of process-log runs."""
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

TIME_COLUMN = "Time"
PROGRAM_COLUMN = "Program"
TIME_FORMAT = "%Y/%m/%d %H:%M:%S"

# Columns that are text/categorical, never plotted as a numeric series.
CATEGORICAL_COLUMNS = {"Auto Action", "Program", "651C Gauge"}

# Channels the user wants viewed together (pressure-control group).
PRESSURE_GROUP_NUMERIC = ["Tube Pressure", "651C Pre", "651C Ang"]
PRESSURE_GROUP_LABEL_COLUMN = "651C Gauge"

# Comparison-mode runs are aligned on when this PV first reaches its SV
# (i.e. when the growth temperature is reached), not on run start time.
ALIGNMENT_PV_COLUMN = "Heater PV"
ALIGNMENT_SV_COLUMN = "Heater SV"


@dataclass(frozen=True)
class RunMetadata:
    path: str
    start_time: pd.Timestamp
    end_time: pd.Timestamp
    row_count: int
    first_program: str


def discover_csv_files(root_folder: str) -> list[str]:
    root = Path(root_folder)
    if not root.is_dir():
        return []
    return sorted(str(p) for p in root.rglob("*.csv"))


def _file_signature(path: str) -> float:
    return Path(path).stat().st_mtime


@st.cache_data(show_spinner=False)
def load_run_dataframe(path: str, _mtime: float) -> pd.DataFrame:
    """Parse a run CSV. `_mtime` is a cache-busting key, not used directly."""
    df = pd.read_csv(path, on_bad_lines="skip", engine="python")
    df[TIME_COLUMN] = pd.to_datetime(df[TIME_COLUMN], format=TIME_FORMAT, errors="coerce")
    df = df.dropna(subset=[TIME_COLUMN])
    numeric_cols = [c for c in df.columns if c not in CATEGORICAL_COLUMNS and c != TIME_COLUMN]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_run(path: str) -> pd.DataFrame:
    return load_run_dataframe(path, _file_signature(path))


def _parse_time_field(fields: list[str], time_idx: int) -> pd.Timestamp | None:
    if time_idx >= len(fields):
        return None
    try:
        return pd.to_datetime(fields[time_idx], format=TIME_FORMAT)
    except (ValueError, TypeError):
        return None


def _scan_metadata_from_file(path: str) -> RunMetadata | None:
    """Cheap metadata scan: reads text lines only, no pandas parsing.

    Listing hundreds of runs by fully parsing every CSV (all columns,
    type-coerced) is far more work than the list view needs -- this reads
    just the first/last row and a line count.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        header_line = f.readline()
        if not header_line:
            return None
        columns = header_line.rstrip("\r\n").split(",")
        try:
            time_idx = columns.index(TIME_COLUMN)
            program_idx = columns.index(PROGRAM_COLUMN)
        except ValueError:
            return None

        first_line = None
        last_line = None
        row_count = 0
        for raw_line in f:
            line = raw_line.rstrip("\r\n")
            if not line:
                continue
            row_count += 1
            if first_line is None:
                first_line = line
            last_line = line

    if first_line is None:
        return None

    first_fields = first_line.split(",")
    start_time = _parse_time_field(first_fields, time_idx)
    if start_time is None:
        return None
    end_time = _parse_time_field(last_line.split(","), time_idx) or start_time
    first_program = first_fields[program_idx] if program_idx < len(first_fields) else ""

    return RunMetadata(
        path=path, start_time=start_time, end_time=end_time,
        row_count=row_count, first_program=first_program,
    )


@st.cache_data(show_spinner=False)
def _cached_scan_metadata(path: str, _mtime: float) -> RunMetadata | None:
    """`_mtime` is a cache-busting key, not used directly."""
    return _scan_metadata_from_file(path)


def get_run_metadata(path: str) -> RunMetadata | None:
    return _cached_scan_metadata(path, _file_signature(path))


def scan_folder(root_folder: str) -> list[RunMetadata]:
    runs = []
    for path in discover_csv_files(root_folder):
        meta = get_run_metadata(path)
        if meta is not None:
            runs.append(meta)
    return sorted(runs, key=lambda r: r.start_time, reverse=True)


def detect_pv_sv_pairs(columns: list[str]) -> list[tuple[str, str, str]]:
    """Return (pair_name, pv_column, sv_column) for every matched PV/SV pair."""
    pairs = []
    col_set = set(columns)
    for col in columns:
        if col.endswith(" PV"):
            prefix = col[: -len(" PV")]
            sv_col = f"{prefix} SV"
            if sv_col in col_set:
                pairs.append((prefix, col, sv_col))
    return pairs


def get_plain_numeric_channels(columns: list[str], pv_sv_pairs: list[tuple[str, str, str]]) -> list[str]:
    """Numeric channels that are not part of a PV/SV pair."""
    paired_cols = {pv for _, pv, _ in pv_sv_pairs} | {sv for _, _, sv in pv_sv_pairs}
    return [
        c for c in columns
        if c not in CATEGORICAL_COLUMNS and c != TIME_COLUMN and c not in paired_cols
    ]

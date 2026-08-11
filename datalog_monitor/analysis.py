"""Summary statistics and PV/SV out-of-tolerance detection."""
import pandas as pd

from .scanner import TIME_COLUMN

SV_ZERO_EPSILON = 1e-6


def compute_summary_stats(df: pd.DataFrame, channels: list[str]) -> pd.DataFrame:
    rows = []
    for channel in channels:
        if channel not in df.columns:
            continue
        series = df[channel].dropna()
        if series.empty:
            continue
        rows.append({
            "Channel": channel,
            "Min": series.min(),
            "Max": series.max(),
            "Avg": series.mean(),
        })
    return pd.DataFrame(rows)


def compute_deviation_pct(df: pd.DataFrame, pv_col: str, sv_col: str) -> pd.Series:
    """Signed % deviation of PV from SV; NaN where SV is ~0 (undefined)."""
    pv = df[pv_col]
    sv = df[sv_col]
    deviation = pd.Series(index=df.index, dtype=float)
    valid = sv.abs() > SV_ZERO_EPSILON
    deviation[valid] = (pv[valid] - sv[valid]) / sv[valid] * 100
    deviation[~valid] = float("nan")
    return deviation


def find_violation_mask(deviation_pct: pd.Series, tolerance_pct: float) -> pd.Series:
    return deviation_pct.abs() > tolerance_pct


def find_violation_segments(df: pd.DataFrame, pair_name: str, mask: pd.Series, deviation_pct: pd.Series) -> list[dict]:
    """Collapse a boolean out-of-tolerance mask into contiguous violation segments."""
    segments = []
    in_violation = False
    seg_start_idx = None
    prev_idx = None
    for idx, flagged in zip(df.index, mask):
        if flagged and not in_violation:
            in_violation = True
            seg_start_idx = idx
        elif not flagged and in_violation:
            in_violation = False
            segments.append(_build_segment(df, pair_name, deviation_pct, seg_start_idx, prev_idx))
        prev_idx = idx
    if in_violation:
        segments.append(_build_segment(df, pair_name, deviation_pct, seg_start_idx, prev_idx))
    return segments


def _build_segment(df, pair_name, deviation_pct, start_idx, end_idx) -> dict:
    seg_slice = deviation_pct.loc[start_idx:end_idx]
    start_time = df.loc[start_idx, TIME_COLUMN]
    end_time = df.loc[end_idx, TIME_COLUMN]
    return {
        "Channel": pair_name,
        "Start": start_time,
        "End": end_time,
        "Duration (s)": (end_time - start_time).total_seconds(),
        "Max Deviation (%)": seg_slice.abs().max(),
    }


def find_final_plateau_start(df: pd.DataFrame, column: str) -> pd.Timestamp | None:
    """First timestamp of the *last* run of rows sitting at the column's max value.

    A setpoint column can sit at its ceiling value from row 0 (a static config
    value logged before the real ramp begins), so the first occurrence of the
    max is a trivial early match. Taking the last upward crossing into the max
    instead finds the genuine "settled at the final setpoint" moment.
    """
    target = df[column].max()
    if pd.isna(target):
        return None
    at_max = df[column] >= target
    rising_edges = at_max & ~at_max.shift(1, fill_value=False)
    if not rising_edges.any():
        return None
    last_edge_idx = df.index[rising_edges][-1]
    return df.loc[last_edge_idx, TIME_COLUMN]


def compute_all_violations(df: pd.DataFrame, pv_sv_pairs: list[tuple[str, str, str]], thresholds: dict, get_tolerance_pct) -> tuple[pd.DataFrame, dict]:
    """Returns (violations_table, {pair_name: (mask, deviation_pct)}) for selected pairs."""
    all_segments = []
    masks = {}
    for pair_name, pv_col, sv_col in pv_sv_pairs:
        if pv_col not in df.columns or sv_col not in df.columns:
            continue
        tolerance_pct = get_tolerance_pct(thresholds, pair_name)
        deviation_pct = compute_deviation_pct(df, pv_col, sv_col)
        mask = find_violation_mask(deviation_pct, tolerance_pct)
        masks[pair_name] = (mask, deviation_pct)
        all_segments.extend(find_violation_segments(df, pair_name, mask, deviation_pct))
    violations_df = pd.DataFrame(all_segments)
    if not violations_df.empty:
        violations_df = violations_df.sort_values("Start")
    return violations_df, masks

"""Check whether a run's datalog is consistent with its paired runcard.

Three independent checks, all anchored on the datalog's "backbone" -- the
Wait / Pumping Forward / End blocks, which are the only commands that
reliably occupy their own slot in the Program column (see runcard.py for
why):

- Sequence: the runcard's backbone command order vs. the datalog's actual
  backbone block order, aligned so one missing/extra step doesn't cascade
  into spurious mismatches for everything after it. A recipe repeats "Wait"
  many times with different programmed durations, so name alone can't tell
  two Waits apart -- the alignment uses duration closeness as a tiebreaker
  (see _merge_cost). It also allows up to _MAX_MERGE consecutive same-name
  runcard commands to match a *single* datalog block, since an instant
  command between two Waits sometimes doesn't get its own Program-column
  sample and the two Waits show up as one continuous block -- but only when
  that's cheaper than matching them separately, so a real, cleanly-sampled
  run isn't forced into a false merge.
- Timing: for matched Wait groups, summed programmed vs. actual duration.
- Setpoints: every instant command (MFC/PC) is checked against its target
  datalog column at the *end* of its matched block -- giving it the most
  possible time to have taken effect, regardless of whether it ever got its
  own Program-column sample. Ramp commands (Heater/P1/P2_Heater Ramp),
  Stage Rot, and Accumulation PC1/2 are excluded -- see
  runcard.target_column for why each doesn't reduce to a simple equality
  check.
"""
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from . import runcard as rc
from .scanner import PROGRAM_COLUMN, TIME_COLUMN

# MFC/PC and pressure targets can legitimately be commanded to exactly zero;
# percentage deviation is undefined there, so a zero target is checked
# against this absolute floor (engineering units: sccm / Torr / rpm) instead.
ZERO_TARGET_ABS_FLOOR = 0.5

_INF = float("inf")
_GAP_COST = 1.0
# How many consecutive same-name runcard commands may collapse onto one
# datalog block. 1Hz sampling can only plausibly swallow a couple of
# back-to-back instant commands, so this stays small and cheap (O(n*m*k)).
_MAX_MERGE = 4


@dataclass(frozen=True)
class SequenceIssue:
    kind: str  # "replace" | "delete" | "insert"
    position: int
    runcard_steps: list[str]
    datalog_steps: list[str]


@dataclass(frozen=True)
class TimingIssue:
    step_name: str
    position: int
    programmed_sec: float
    actual_sec: float
    start_time: pd.Timestamp


@dataclass(frozen=True)
class SetpointIssue:
    command_name: str
    column: str
    expected: float
    actual: float
    check_time: pd.Timestamp


@dataclass(frozen=True)
class CheckResult:
    status: str  # "Pass" | "Fail" | "Incomplete"
    matched_steps: int
    total_steps: int
    sequence_issues: list[SequenceIssue] = field(default_factory=list)
    timing_issues: list[TimingIssue] = field(default_factory=list)
    setpoint_issues: list[SetpointIssue] = field(default_factory=list)


def _split_into_buckets(
    commands: list[rc.RuncardCommand],
) -> tuple[list[rc.RuncardCommand], list[list[rc.RuncardCommand]]]:
    """Split the runcard's command list into its backbone commands, plus the
    instant commands preceding each one (buckets[i] precedes backbone[i])."""
    backbone = []
    buckets = []
    current_bucket = []
    for cmd in commands:
        if cmd.name in rc.BACKBONE_COMMANDS:
            buckets.append(current_bucket)
            backbone.append(cmd)
            current_bucket = []
        else:
            current_bucket.append(cmd)
    buckets.append(current_bucket)  # trailing bucket after the last backbone command (always empty)
    return backbone, buckets


def _build_backbone_blocks(df: pd.DataFrame) -> list[dict]:
    """Run-length-encode the Program column, keeping only backbone-type blocks."""
    names = df[PROGRAM_COLUMN].tolist()
    times = df[TIME_COLUMN].tolist()
    indices = df.index.tolist()

    blocks = []
    start = 0
    for i in range(1, len(names) + 1):
        if i == len(names) or names[i] != names[start]:
            name = names[start]
            if name in rc.BACKBONE_COMMANDS:
                blocks.append({
                    "name": name,
                    "start_idx": indices[start],
                    "start_time": times[start],
                    "end_idx": indices[i - 1],
                    "n_rows": i - start,
                })
            start = i
    return blocks


def _merge_cost(cmds: list[rc.RuncardCommand], block: dict) -> float:
    """Cost of matching a run of 1+ consecutive same-name runcard commands to one block.

    Different names never pair (infinite cost -- always reported as a real
    sequence discrepancy, never silently substituted). Same-name Wait runs
    are disambiguated by duration closeness, but the cost is capped below
    1.0 -- always cheaper than a delete+insert (cost 2) -- so a huge timing
    deviation still gets matched (and then flagged by the timing check)
    rather than hidden behind a sequence "delete".
    """
    name = cmds[0].name
    if name != block["name"]:
        return _INF
    if name != "Wait":
        return 0.0
    programmed = sum(rc.wait_duration_seconds(c) for c in cmds)
    actual = float(block["n_rows"])
    if programmed <= 0:
        return 0.0
    return abs(actual - programmed) / max(actual, programmed, 1.0)


def _align_backbone(backbone_cmds: list[rc.RuncardCommand], backbone_blocks: list[dict]) -> list[tuple]:
    """Weighted edit-distance alignment of runcard backbone commands to datalog blocks.

    Returns a list of ("match", [runcard_idx, ...], block_idx) |
    ("delete", runcard_idx, None) | ("insert", None, block_idx), covering
    every element of both sequences in order. A "match" run of runcard
    indices is usually length 1, but can be longer (see _MAX_MERGE).
    """
    n, m = len(backbone_cmds), len(backbone_blocks)
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    choice = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i * _GAP_COST
    for j in range(1, m + 1):
        dp[0][j] = j * _GAP_COST

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best_cost = dp[i - 1][j] + _GAP_COST
            best_choice = ("delete", 1)
            if dp[i][j - 1] + _GAP_COST < best_cost:
                best_cost = dp[i][j - 1] + _GAP_COST
                best_choice = ("insert", 1)
            for k in range(1, min(i, _MAX_MERGE) + 1):
                names_agree = len({c.name for c in backbone_cmds[i - k:i]}) == 1
                if not names_agree:
                    break  # longer k only ever spans more names, never fewer
                cost = _merge_cost(backbone_cmds[i - k:i], backbone_blocks[j - 1])
                if cost < _INF and dp[i - k][j - 1] + cost < best_cost:
                    best_cost = dp[i - k][j - 1] + cost
                    best_choice = ("match", k)
            dp[i][j] = best_cost
            choice[i][j] = best_choice

    ops = []
    i, j = n, m
    while i > 0 or j > 0:
        if i == 0:
            ops.append(("insert", None, j - 1))
            j -= 1
            continue
        if j == 0:
            ops.append(("delete", i - 1, None))
            i -= 1
            continue
        kind, step = choice[i][j]
        if kind == "match":
            ops.append(("match", list(range(i - step, i)), j - 1))
            i -= step
            j -= 1
        elif kind == "delete":
            ops.append(("delete", i - 1, None))
            i -= 1
        else:
            ops.append(("insert", None, j - 1))
            j -= 1
    ops.reverse()
    return ops


def _timing_mismatch(programmed: float, actual: float, tolerance_pct: float, floor_sec: float) -> bool:
    diff = abs(actual - programmed)
    if diff <= floor_sec:
        return False
    if programmed <= 0:
        return True
    return diff / programmed * 100 > tolerance_pct


def _setpoint_mismatch(target: float, actual: float, tolerance_pct: float) -> bool:
    if abs(target) < 1e-9:
        return abs(actual) > ZERO_TARGET_ABS_FLOOR
    return abs(actual - target) / abs(target) * 100 > tolerance_pct


def _pair_name_for_column(column: str) -> str:
    return column[: -len(" SV")] if column.endswith(" SV") else column


def check_run(
    commands: list[rc.RuncardCommand],
    df: pd.DataFrame,
    timing_tolerance_pct: float,
    timing_floor_sec: float,
    get_setpoint_tolerance_pct: Callable[[str], float],
) -> CheckResult:
    backbone_cmds, buckets = _split_into_buckets(commands)
    backbone_blocks = _build_backbone_blocks(df)
    ops = _align_backbone(backbone_cmds, backbone_blocks)

    sequence_issues = []
    timing_issues = []
    setpoint_issues = []
    matched_indices: set[int] = set()

    i = 0
    while i < len(ops):
        tag = ops[i][0]
        if tag == "match":
            _, runcard_idxs, block_idx = ops[i]
            block = backbone_blocks[block_idx]
            matched_indices.update(runcard_idxs)
            group_cmds = [backbone_cmds[k] for k in runcard_idxs]

            if group_cmds[0].name == "Wait":
                programmed = sum(rc.wait_duration_seconds(c) for c in group_cmds)
                actual = float(block["n_rows"])
                if _timing_mismatch(programmed, actual, timing_tolerance_pct, timing_floor_sec):
                    timing_issues.append(TimingIssue(
                        step_name=group_cmds[0].name, position=runcard_idxs[0],
                        programmed_sec=programmed, actual_sec=actual, start_time=block["start_time"],
                    ))

            for k in runcard_idxs:
                for instant_cmd in buckets[k]:
                    column = rc.target_column(instant_cmd)
                    if column is None or column not in df.columns:
                        continue
                    target = rc.target_value(instant_cmd)
                    if target is None:
                        continue
                    actual_value = df.loc[block["end_idx"], column]
                    if pd.isna(actual_value):
                        continue
                    tolerance_pct = get_setpoint_tolerance_pct(_pair_name_for_column(column))
                    if _setpoint_mismatch(target, float(actual_value), tolerance_pct):
                        setpoint_issues.append(SetpointIssue(
                            command_name=f"{instant_cmd.name} {' '.join(instant_cmd.params)}".strip(),
                            column=column, expected=target, actual=float(actual_value),
                            check_time=block["start_time"],
                        ))
            i += 1
            continue

        run_runcard_idx = []
        run_block_idx = []
        while i < len(ops) and ops[i][0] != "match":
            tag2, a, b = ops[i]
            (run_runcard_idx if tag2 == "delete" else run_block_idx).append(a if tag2 == "delete" else b)
            i += 1
        is_trailing_incomplete = i == len(ops) and not run_block_idx
        if is_trailing_incomplete:
            continue
        kind = "replace" if run_runcard_idx and run_block_idx else ("delete" if run_runcard_idx else "insert")
        position = run_runcard_idx[0] if run_runcard_idx else (max(matched_indices) + 1 if matched_indices else 0)
        sequence_issues.append(SequenceIssue(
            kind=kind, position=position,
            runcard_steps=[backbone_cmds[k].name for k in run_runcard_idx],
            datalog_steps=[backbone_blocks[k]["name"] for k in run_block_idx],
        ))

    is_incomplete = len(matched_indices) < len(backbone_cmds)
    if sequence_issues or timing_issues or setpoint_issues:
        status = "Fail"
    elif is_incomplete:
        status = "Incomplete"
    else:
        status = "Pass"

    return CheckResult(
        status=status, matched_steps=len(matched_indices), total_steps=len(backbone_cmds),
        sequence_issues=sequence_issues, timing_issues=timing_issues, setpoint_issues=setpoint_issues,
    )

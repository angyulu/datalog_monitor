"""Parsing of runcard recipe CSVs and mapping their commands to datalog columns.

A runcard is an ordered list of commands (Wait, Stage Rot, Heater Ramp, MFC/PC, ...).
Commands split into two kinds:

- "Backbone" commands (Wait, Pumping Forward, End) are the only ones that reliably
  show up as their own block in the datalog's Program column -- they hold for multiple
  seconds. Everything else, including Heater Soak (confirmed empirically: across 13
  real runs it showed up as its own Program value exactly once), executes faster than
  the 1Hz log interval and can land between samples, so it never gets a dedicated
  Program-column entry.
- Every other command is "instant": it pokes a setpoint and the recipe moves on
  immediately. These can only be verified by checking the datalog's SV column value,
  never by looking for their own slot in the Program column.
"""
import csv
import re
from dataclasses import dataclass

BACKBONE_COMMANDS = {"Wait", "Pumping Forward", "End"}

_RAMP_COMMANDS = {"Heater Ramp", "P1_Heater Ramp", "P2_Heater Ramp"}

_MFC_RE = re.compile(r"^MFC-(\d+)")
_PC_RE = re.compile(r"^PC-(\d+)$")
_ACCUMULATION_RE = re.compile(r"^Accumulation PC(\d+)$")


@dataclass(frozen=True)
class RuncardCommand:
    index: int
    name: str
    params: tuple[str, ...]


def parse_runcard(path: str) -> list[RuncardCommand]:
    """Parse a runcard CSV into its ordered command list, stopping at End.

    Everything after End is padding ("--,--,--" filler rows out to a fixed
    file length) and carries no recipe information.
    """
    commands = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            row = [c.strip() for c in row]
            if len(row) < 3 or row[0] in ("--", ""):
                continue
            commands.append(RuncardCommand(index=len(commands), name=row[0], params=tuple(row[1:])))
            if row[0] == "End":
                break
    return commands


def wait_duration_seconds(cmd: RuncardCommand) -> float:
    """Seconds a Wait command blocks for; the runcard expresses it as Sec or Min."""
    unit, value = cmd.params[0], cmd.params[1]
    duration = float(value)
    return duration * 60 if unit.lower().startswith("min") else duration


def target_column(cmd: RuncardCommand) -> str | None:
    """Datalog SV column this instant command's value should show up in.

    Returns None for backbone commands and for instant commands that can't be
    verified by a simple equality check against a column:
    - RTV Pressure Ctrl, Pumping Forward -- Tube Pressure has no paired SV
      column at all.
    - Heater Ramp / P1_Heater Ramp / P2_Heater Ramp -- the SV climbs
      gradually over the ramp's declared duration rather than jumping to
      target, so "does it equal target yet" depends on how much of the ramp
      has elapsed, not on correctness. Needs a rate-of-change check instead.
    - Stage Rot -- there's no PV/SV pair for it (just one "Stage Rot"
      column), and real data shows it lags the commanded speed for several
      seconds (mechanical spin-up), so it behaves like a measurement, not an
      instant setpoint echo.
    - Accumulation PC1/PC2 -- despite sharing naming with PC-1/PC-2, real
      data shows they do *not* write to the P1 SV/P2 SV columns (those stay
      at whatever the last MFC/PC PC-1/PC-2 command set) -- so whatever
      register they do target isn't visible in this datalog schema.
    """
    if cmd.name in _RAMP_COMMANDS or cmd.name == "Stage Rot" or _ACCUMULATION_RE.match(cmd.name):
        return None
    if cmd.name == "MFC/PC":
        channel = cmd.params[0] if cmd.params else ""
        mfc_match = _MFC_RE.match(channel)
        if mfc_match:
            return f"MFC-{mfc_match.group(1)} SV"
        pc_match = _PC_RE.match(channel)
        if pc_match:
            return f"P{pc_match.group(1)} SV"
        return None
    return None


def target_value(cmd: RuncardCommand) -> float | None:
    """Commanded numeric value for an instant command, or None if not parseable."""
    if cmd.name == "MFC/PC":
        try:
            return float(cmd.params[1])
        except (IndexError, ValueError):
            return None
    try:
        return float(cmd.params[0])
    except (IndexError, ValueError):
        return None

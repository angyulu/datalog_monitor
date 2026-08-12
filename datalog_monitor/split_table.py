"""Builds a one-row-per-runcard summary table, self-contained -- every
column is a value already computed for the Runcard View chart (growth
window, peak T, gas chemistry, pressures, spin, P1/P2 heater temps at
growth), not a mapping onto any external spreadsheet layout.

Gas-species columns are dynamic: whichever species actually turn up across
the runcards being shown get their own column, so a different tool's
recipe (different gases) just produces different columns automatically.
"""
import pandas as pd

from . import growth_window as gw
from . import runcard as rc
from . import runcard_svg as rsvg

_FIXED_CHANNEL_COLUMNS = [
    ("PC-1", "PC-1 (Torr)"),
    ("PC-2", "PC-2 (Torr)"),
    ("RTV", "RTV (Torr)"),
    ("Spin", "Spin (rpm)"),
]


def _round_or_blank(value: float | None, digits: int = 2):
    return "" if value is None else round(value, digits)


def discover_species(commands_list: list[list[rc.RuncardCommand]]) -> list[str]:
    """Every gas species seen across `commands_list`, in first-seen order."""
    species: list[str] = []
    for commands in commands_list:
        timeline = gw.build_timeline(commands)
        for _t, name, _v in timeline.mfc_events:
            sp = gw.get_species(name)
            if sp not in species:
                species.append(sp)
    return species


def build_row(commands: list[rc.RuncardCommand], run_id: str, species_columns: list[str]) -> dict:
    profile = gw.build_profile(commands)
    growth = profile.growth
    has_growth = growth.start_s is not None

    row = {
        "Run": run_id,
        "Total time (min)": round(profile.timeline.total_time / 60, 1),
        "Peak T (°C)": round(growth.peak_temp_c, 1),
        "Growth window (min)": f"{growth.start_s / 60:.0f}–{growth.end_s / 60:.0f}" if has_growth else "",
        "Growth duration (min)": round(growth.duration_min, 1) if has_growth else "",
        "P1 (°C)": _round_or_blank(gw.fixed_channel_value_at_growth_mid(profile, "P1"), 1),
        "P2 (°C)": _round_or_blank(gw.fixed_channel_value_at_growth_mid(profile, "P2"), 1),
    }
    for channel_id, label in _FIXED_CHANNEL_COLUMNS:
        row[label] = _round_or_blank(gw.fixed_channel_value_at_growth_mid(profile, channel_id), 1)
    for species in species_columns:
        row[f"{species} (sccm)"] = _round_or_blank(gw.species_value_at_growth_mid(profile, species), 2)
    return row


def build_table(runcard_paths: list[str]) -> pd.DataFrame:
    """One row per path, in the given order -- serves Single (len==1) and
    Compare (len==N) identically, no mode branching. The species column set
    is the union across every path given, so every row shares the same
    columns even if a particular runcard doesn't use a given species.
    """
    commands_list = [rc.parse_runcard(p) for p in runcard_paths]
    species_columns = discover_species(commands_list)
    rows = [
        build_row(commands, rsvg.derive_run_id(path), species_columns)
        for path, commands in zip(runcard_paths, commands_list)
    ]
    return pd.DataFrame(rows)

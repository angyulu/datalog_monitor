"""Runcard timeline reconstruction and growth-window detection.

Ported from Example/Runcard_datalog_0810/render_runcard.py's build_timeline /
build_temp_trace / build_aux_trace / find_growth (that script must stay
untouched -- it's a standalone CLI reference), adapted to consume
RuncardCommand objects from runcard.parse_runcard instead of raw CSV rows.

The "growth window" is the time range where the main heater trace sits
within GROWTH_BAND_C of its run-wide peak -- this is the single shared
computation both the split-table feature and the runcard SVG view need, so
it lives here once rather than being re-derived in either.
"""
import math
from dataclasses import dataclass

from . import runcard as rc

CHECK_STATUS_SECONDS = 10
ROOM_TEMP_C = 25.0
GROWTH_BAND_C = 5.0
COOLDOWN_TAU_SEC = 2400
COOLDOWN_STEP_SEC = 60

# Value must clear this to count as "on" -- matches render_runcard.py's own
# thresholds (MFC channels use a slightly higher floor since they idle at a
# small nonzero purge flow; PC/RTV/Spin idle at exactly 0).
_MFC_ON_FLOOR = 0.01
_ZERO_FLOOR = 0.0


@dataclass(frozen=True)
class Timeline:
    total_time: float
    heater_ramps: list[tuple[float, float, float, float]]
    p1_ramps: list[tuple[float, float, float, float]]
    p2_ramps: list[tuple[float, float, float, float]]
    mfc_events: list[tuple[float, str, float]]
    pc_events: list[tuple[float, str, float]]
    rtv_events: list[tuple[float, float]]
    spin_events: list[tuple[float, float]]
    heater_off_t: float | None


@dataclass(frozen=True)
class GrowthWindow:
    start_s: float | None
    end_s: float | None
    peak_temp_c: float

    @property
    def mid_s(self) -> float | None:
        if self.start_s is None or self.end_s is None:
            return None
        return (self.start_s + self.end_s) / 2

    @property
    def duration_min(self) -> float:
        if self.start_s is None or self.end_s is None:
            return 0.0
        return (self.end_s - self.start_s) / 60


@dataclass(frozen=True)
class RuncardProfile:
    timeline: Timeline
    temp_trace: list[tuple[float, float]]
    p1_trace: list[tuple[float, float]]
    p2_trace: list[tuple[float, float]]
    growth: GrowthWindow


def build_timeline(commands: list[rc.RuncardCommand]) -> Timeline:
    t = 0.0
    heater_ramps: list[tuple[float, float, float, float]] = []
    p1_ramps: list[tuple[float, float, float, float]] = []
    p2_ramps: list[tuple[float, float, float, float]] = []
    mfc_events: list[tuple[float, str, float]] = []
    pc_events: list[tuple[float, str, float]] = []
    rtv_events: list[tuple[float, float]] = []
    spin_events: list[tuple[float, float]] = []
    heater_off_t: float | None = None
    cur_T = ROOM_TEMP_C
    cur_p1 = ROOM_TEMP_C
    cur_p2 = ROOM_TEMP_C

    for cmd in commands:
        name = cmd.name
        if name == "Wait":
            t += rc.wait_duration_seconds(cmd)
        elif name == "Check Status":
            t += CHECK_STATUS_SECONDS
        elif name == "Heater Ramp":
            tgt, dur = float(cmd.params[0]), float(cmd.params[1])
            heater_ramps.append((t, cur_T, tgt, dur))
            cur_T = tgt
        elif name == "P1_Heater Ramp":
            tgt, dur = float(cmd.params[0]), float(cmd.params[1])
            p1_ramps.append((t, cur_p1, tgt, dur))
            cur_p1 = tgt
        elif name == "P2_Heater Ramp":
            tgt, dur = float(cmd.params[0]), float(cmd.params[1])
            p2_ramps.append((t, cur_p2, tgt, dur))
            cur_p2 = tgt
        elif name == "Heater Soak":
            if heater_off_t is None:
                heater_off_t = t
        elif name == "MFC/PC":
            channel, val = cmd.params[0], float(cmd.params[1])
            (pc_events if channel.startswith("PC-") else mfc_events).append((t, channel, val))
        elif name == "RTV Pressure Ctrl":
            rtv_events.append((t, float(cmd.params[1])))
        elif name.startswith("Accumulation PC") or name.startswith("Accumulation_PC"):
            pc_num = "".join(filter(str.isdigit, name.replace("Accumulation", "")))
            pc_events.append((t, f"PC-{pc_num}", float(cmd.params[0])))
        elif name == "Stage Rot":
            spin_events.append((t, float(cmd.params[0])))

    return Timeline(
        total_time=t, heater_ramps=heater_ramps, p1_ramps=p1_ramps, p2_ramps=p2_ramps,
        mfc_events=mfc_events, pc_events=pc_events, rtv_events=rtv_events,
        spin_events=spin_events, heater_off_t=heater_off_t,
    )


def build_temp_trace(
    ramps: list[tuple[float, float, float, float]], off_t: float | None, total: float,
) -> list[tuple[float, float]]:
    pts = [(0.0, ROOM_TEMP_C)]
    for ts, _T0, T1, dur in ramps:
        if pts[-1][0] < ts:
            pts.append((ts, pts[-1][1]))
        pts.append((ts + dur, T1))
    if off_t is not None:
        last_T = pts[-1][1]
        if pts[-1][0] < off_t:
            pts.append((off_t, last_T))
        tn = off_t
        while tn < total:
            tn += COOLDOWN_STEP_SEC
            tn = min(tn, total)
            pts.append((tn, ROOM_TEMP_C + (last_T - ROOM_TEMP_C) * math.exp(-(tn - off_t) / COOLDOWN_TAU_SEC)))
    return pts


def build_aux_trace(ramps: list[tuple[float, float, float, float]], total: float) -> list[tuple[float, float]]:
    if not ramps:
        return []
    pts = [(0.0, ROOM_TEMP_C)]
    for ts, _T0, T1, dur in ramps:
        if pts[-1][0] < ts:
            pts.append((ts, pts[-1][1]))
        pts.append((ts + dur, T1))
    if pts[-1][0] < total:
        pts.append((total, pts[-1][1]))
    return pts


def find_growth_window(temp_trace: list[tuple[float, float]], heater_off_t: float | None) -> GrowthWindow:
    peak = max(T for _t, T in temp_trace)
    thresh = peak - GROWTH_BAND_C
    start_s = end_s = None
    for t, T in temp_trace:
        if heater_off_t and t > heater_off_t:
            break
        if T >= thresh:
            if start_s is None:
                start_s = t
            end_s = t
    return GrowthWindow(start_s=start_s, end_s=end_s, peak_temp_c=peak)


def build_profile(commands: list[rc.RuncardCommand]) -> RuncardProfile:
    timeline = build_timeline(commands)
    temp_trace = build_temp_trace(timeline.heater_ramps, timeline.heater_off_t, timeline.total_time)
    p1_trace = build_aux_trace(timeline.p1_ramps, timeline.total_time)
    p2_trace = build_aux_trace(timeline.p2_ramps, timeline.total_time)
    growth = find_growth_window(temp_trace, timeline.heater_off_t)
    return RuncardProfile(timeline=timeline, temp_trace=temp_trace, p1_trace=p1_trace, p2_trace=p2_trace, growth=growth)


def get_species(channel_name: str) -> str:
    parts = channel_name.split()
    return parts[-1] if len(parts) >= 2 else channel_name


def _first_channel_for_species(events: list[tuple[float, str, float]], species: str) -> str | None:
    seen: list[str] = []
    for _t, name, _v in events:
        if name not in seen:
            seen.append(name)
    for name in seen:
        if get_species(name) == species:
            return name
    return None


def _named_event_value_at_or_before(events: list[tuple[float, str, float]], name: str, t: float) -> float | None:
    value = None
    for et, en, ev in events:
        if en == name and et <= t:
            value = ev
    return value


def _event_value_at_or_before(events: list[tuple[float, float]], t: float) -> float | None:
    value = None
    for et, ev in events:
        if et <= t:
            value = ev
    return value


def _trace_value_at_or_before(points: list[tuple[float, float]], t: float) -> float | None:
    value = None
    for pt, pv in points:
        if pt <= t:
            value = pv
    return value


def species_value_at_growth_mid(profile: RuncardProfile, species: str) -> float | None:
    """Value of whichever MFC channel currently carries `species` in this recipe,
    at the growth-window midpoint. None if the species isn't present in this
    recipe, or there's no growth window, or the value never clears the "on" floor.
    """
    mid = profile.growth.mid_s
    if mid is None:
        return None
    channel = _first_channel_for_species(profile.timeline.mfc_events, species)
    if channel is None:
        return None
    value = _named_event_value_at_or_before(profile.timeline.mfc_events, channel, mid)
    return value if value is not None and value > _MFC_ON_FLOOR else None


def fixed_channel_value_at_growth_mid(profile: RuncardProfile, channel_id: str) -> float | None:
    """Value of a non-gas channel at the growth-window midpoint.

    channel_id must be one of "Heater", "P1", "P2", "PC-1", "PC-2", "RTV", "Spin".
    "Heater" returns the run-wide peak temp directly (matching render_runcard.py's
    summary box, which uses peak_T rather than an interpolated value-at-mid).
    """
    mid = profile.growth.mid_s
    if mid is None:
        return None
    tl = profile.timeline
    if channel_id == "Heater":
        return profile.growth.peak_temp_c
    if channel_id == "P1":
        return _trace_value_at_or_before(profile.p1_trace, mid)
    if channel_id == "P2":
        return _trace_value_at_or_before(profile.p2_trace, mid)
    if channel_id in ("PC-1", "PC-2"):
        value = _named_event_value_at_or_before(tl.pc_events, channel_id, mid)
        return value if value is not None and value > _ZERO_FLOOR else None
    if channel_id == "RTV":
        value = _event_value_at_or_before(tl.rtv_events, mid)
        return value if value is not None and value > _ZERO_FLOOR else None
    if channel_id == "Spin":
        value = _event_value_at_or_before(tl.spin_events, mid)
        return value if value is not None and value > _ZERO_FLOOR else None
    raise ValueError(f"Unknown fixed channel: {channel_id!r}")

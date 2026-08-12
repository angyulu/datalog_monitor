"""Renders a runcard's process profile as an SVG -- ported from
Example/Runcard_datalog_0810/render_runcard.py (which must stay untouched;
it's a standalone CLI reference), adapted to take a growth_window.RuncardProfile
instead of a raw tl dict + separately-passed traces. get_species is shared
with growth_window.py rather than redefined here.
"""
import math
import re
from pathlib import Path

from .growth_window import RuncardProfile, get_species

COLORS = {
    'Ar': {'fill': '#c8c8c8', 'stroke': '#999999'},
    'O2': {'fill': '#c5e6c0', 'stroke': '#66aa66'},
    'H2Se': {'fill': '#f5c4d0', 'stroke': '#cc6666'},
    'H2S': {'fill': '#f5deb3', 'stroke': '#cc9900'},
    'H2': {'fill': '#f5a0a0', 'stroke': '#cc5555'},
    'N2': {'fill': '#b0c4de', 'stroke': '#666699'},
}
FALLBACK_COLORS = [{'fill': '#d8b4fe', 'stroke': '#7c3aed'}, {'fill': '#99f6e4', 'stroke': '#0d9488'}]
TEMP_COLOR, P1_COLOR, P2_COLOR = '#d4522a', '#4488cc', '#22886a'
GROWTH_FILL, GROWTH_STROKE = 'rgba(255,182,193,0.18)', '#d4849a'
RTV_COLOR, PC1_COLOR, PC2_COLOR, SPIN_COLOR = '#2c2c54', '#1a8a7a', '#1a5a6a', '#6b7b90'
LABEL_FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
W = 1120
MARGIN = {'left': 90, 'right': 100}
TEMP_AREA_TOP, TEMP_AREA_BOT = 90, 300
BAR_AREA_TOP, BAR_H, BAR_GAP = 340, 24, 6


def hex_to_rgb(h):
    h = h.lstrip('#')
    if len(h) == 3:
        h = h[0] * 2 + h[1] * 2 + h[2] * 2
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(r, g, b):
    return f'#{int(r):02x}{int(g):02x}{int(b):02x}'


def lerp_color(light, dark, frac):
    lr, lg, lb = hex_to_rgb(light)
    dr, dg, db = hex_to_rgb(dark)
    return rgb_to_hex(lr + (dr - lr) * frac, lg + (dg - lg) * frac, lb + (db - lb) * frac)


def make_light(hx, blend=0.7):
    r, g, b = hex_to_rgb(hx)
    return rgb_to_hex(r + (255 - r) * blend, g + (255 - g) * blend, b + (255 - b) * blend)


def get_color(name):
    sp = get_species(name)
    return COLORS.get(sp, FALLBACK_COLORS[hash(name) % len(FALLBACK_COLORS)])


def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def interp_temp(trace, t):
    if t <= trace[0][0]:
        return trace[0][1]
    if t >= trace[-1][0]:
        return trace[-1][1]
    for i in range(len(trace) - 1):
        t0, T0 = trace[i]
        t1, T1 = trace[i + 1]
        if t0 <= t <= t1:
            return T0 + (T1 - T0) * ((t - t0) / (t1 - t0)) if t1 != t0 else T0
    return trace[-1][1]


def build_bars(events, total, threshold=0.05):
    channels, seen = [], set()
    for t, name, val in events:
        if name not in seen:
            channels.append(name)
            seen.add(name)
    bars = {}
    for ch in channels:
        ce = [(t, v) for t, n, v in events if n == ch]
        segs = []
        for i, (t, v) in enumerate(ce):
            if v > threshold:
                te = ce[i + 1][0] if i + 1 < len(ce) else total
                segs.append((t, te, v))
        bars[ch] = segs
    return bars, channels


def build_simple_bars(events, total):
    segs = []
    for i, (t, v) in enumerate(events):
        if v > 0:
            te = events[i + 1][0] if i + 1 < len(events) else total
            segs.append((t, te, v))
    return segs


def derive_run_id(path: str) -> str:
    run_id = Path(path).stem
    if '_' in run_id:
        parts = run_id.split('_')
        if parts[0].isdigit():
            run_id = '_'.join(parts[1:])
    return re.sub(r'_runcard$', '', run_id, flags=re.IGNORECASE).upper()


def render_svg(run_id: str, profile: RuncardProfile) -> tuple[str, dict]:
    tl = profile.timeline
    temp_trace, p1_trace, p2_trace = profile.temp_trace, profile.p1_trace, profile.p2_trace
    total_s = tl.total_time
    total_min = total_s / 60
    gw_start, gw_end, peak_T = profile.growth.start_s, profile.growth.end_s, profile.growth.peak_temp_c
    gw_dur = profile.growth.duration_min

    mfc_bars, mfc_ch = build_bars(tl.mfc_events, total_s)
    pc_bars, pc_ch = build_bars(tl.pc_events, total_s, 0)
    rtv_segs = build_simple_bars(tl.rtv_events, total_s)
    spin_segs = build_simple_bars(tl.spin_events, total_s)

    bar_rows = []
    for ch in mfc_ch:
        bar_rows.append((ch, mfc_bars.get(ch, []), get_color(ch), False))
    if rtv_segs:
        bar_rows.append(('RTV P', rtv_segs, {'fill': RTV_COLOR, 'stroke': RTV_COLOR}, True))
    for ch in pc_ch:
        c = PC1_COLOR if '1' in ch else PC2_COLOR
        bar_rows.append((ch, pc_bars.get(ch, []), {'fill': c, 'stroke': c}, True))
    if spin_segs:
        bar_rows.append(('Spin', [(t, te, f'{v:.0f} rpm') for t, te, v in spin_segs],
                         {'fill': SPIN_COLOR, 'stroke': SPIN_COLOR}, True))

    n_bars = len(bar_rows)
    bars_h = n_bars * (BAR_H + BAR_GAP)
    summary_top = BAR_AREA_TOP + bars_h + 30
    canvas_h = summary_top + 130

    pl, pr = MARGIN['left'], W - MARGIN['right']
    pw = pr - pl

    def tx(t):
        return pl + (t / total_s) * pw

    tmax = max(peak_T + 50, 900)

    def ty(T):
        return TEMP_AREA_BOT - (T / tmax) * (TEMP_AREA_BOT - TEMP_AREA_TOP)

    svg = [f'<svg viewBox="0 0 {W} {canvas_h}" xmlns="http://www.w3.org/2000/svg" font-family="{LABEL_FONT}">']

    svg.append(f'<text x="{pl}" y="40" font-size="22" font-weight="bold" fill="#333">{esc(run_id)} — Recipe profile</text>')
    svg.append(f'<text x="{pr}" y="40" font-size="14" fill="#888" text-anchor="end">{total_min:.0f} min total</text>')

    if gw_start is not None:
        x1, x2 = tx(gw_start), tx(gw_end)
        svg.append(f'<rect x="{x1}" y="{TEMP_AREA_TOP-20}" width="{x2-x1}" height="{TEMP_AREA_BOT-TEMP_AREA_TOP+20}" fill="{GROWTH_FILL}"/>')
        for xv in (x1, x2):
            svg.append(f'<line x1="{xv}" y1="{TEMP_AREA_TOP-20}" x2="{xv}" y2="{TEMP_AREA_BOT}" stroke="{GROWTH_STROKE}" stroke-width="1" stroke-dasharray="4,3"/>')
        svg.append(f'<text x="{(x1+x2)/2}" y="{TEMP_AREA_TOP-25}" font-size="12" fill="{GROWTH_STROKE}" text-anchor="middle" font-style="italic">Growth ({gw_dur:.0f} min @ {peak_T:.0f}°C)</text>')

    svg.append(f'<text x="{pl-10}" y="{TEMP_AREA_TOP-10}" font-size="11" fill="#666" text-anchor="end">Temp (°C)</text>')
    for Tt in [0, 300, int(peak_T)]:
        y = ty(Tt)
        svg.append(f'<line x1="{pl}" y1="{y}" x2="{pr}" y2="{y}" stroke="#eee" stroke-width="0.5"/>')
        svg.append(f'<text x="{pl-8}" y="{y+4}" font-size="10" fill="#999" text-anchor="end">{Tt}</text>')

    p1_final = None
    if p1_trace:
        pts = ' '.join(f'{tx(t):.1f},{ty(T):.1f}' for t, T in p1_trace)
        svg.append(f'<polyline points="{pts}" fill="none" stroke="{P1_COLOR}" stroke-width="1.5" stroke-dasharray="6,4"/>')
        p1_final = p1_trace[-1][1]
        svg.append(f'<text x="{tx(p1_trace[-1][0])+6}" y="{ty(p1_final)+4}" font-size="11" fill="{P1_COLOR}" font-weight="500">P1 ({p1_final:.0f}°C)</text>')

    p2_final = None
    if p2_trace:
        pts = ' '.join(f'{tx(t):.1f},{ty(T):.1f}' for t, T in p2_trace)
        svg.append(f'<polyline points="{pts}" fill="none" stroke="{P2_COLOR}" stroke-width="1.5" stroke-dasharray="4,6"/>')
        p2_final = p2_trace[-1][1]
        yo = 14 if p1_trace else 4
        svg.append(f'<text x="{tx(p2_trace[-1][0])+6}" y="{ty(p2_final)+yo}" font-size="11" fill="{P2_COLOR}" font-weight="500">P2 ({p2_final:.0f}°C)</text>')

    pts = ' '.join(f'{tx(t):.1f},{ty(T):.1f}' for t, T in temp_trace)
    svg.append(f'<polyline points="{pts}" fill="none" stroke="{TEMP_COLOR}" stroke-width="2.5" stroke-linejoin="round"/>')

    skip_sp = {'Ar', 'N2'}
    ch_st = {}
    events = []
    above = True
    for t, name, val in sorted(tl.mfc_events, key=lambda x: x[0]):
        sp = get_species(name)
        if sp in skip_sp:
            ch_st[name] = val
            continue
        prev = ch_st.get(name, 0)
        if t == 0:
            ch_st[name] = val
            continue
        if prev <= 0.05 and val > 0.05:
            events.append((t, sp, 'on'))
        elif prev > 0.05 and val <= 0.05:
            events.append((t, sp, 'off'))
        ch_st[name] = val
    for t_ev, sp, d in events:
        if gw_start and gw_start <= t_ev <= gw_end:
            continue
        Tat = interp_temp(temp_trace, t_ev)
        x = tx(t_ev)
        y = ty(Tat)
        sc = COLORS.get(sp, {'stroke': '#666'})['stroke']
        ly = y - 18 if above else y + 22
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{sc}" opacity="0.7"/>')
        svg.append(f'<text x="{x:.1f}" y="{ly:.1f}" font-size="10" fill="{sc}" text-anchor="middle">{esc(f"{sp} {d} · {Tat:.0f}°C")}</text>')
        above = not above

    bby = BAR_AREA_TOP + bars_h + 10
    svg.append(f'<line x1="{pl}" y1="{bby}" x2="{pr}" y2="{bby}" stroke="#ccc" stroke-width="0.5"/>')
    tt = 0
    while tt <= total_s:
        x = tx(tt)
        svg.append(f'<line x1="{x}" y1="{bby}" x2="{x}" y2="{bby+5}" stroke="#999" stroke-width="0.5"/>')
        svg.append(f'<text x="{x}" y="{bby+18}" font-size="10" fill="#999" text-anchor="middle">{tt/60:.0f}</text>')
        tt += 1800
    svg.append(f'<text x="{(pl+pr)/2}" y="{bby+32}" font-size="11" fill="#888" text-anchor="middle">Time (min)</text>')

    for i, (label, segs, colors, is_p) in enumerate(bar_rows):
        yb = BAR_AREA_TOP + i * (BAR_H + BAR_GAP)
        dx = pl - 12
        dy = yb + BAR_H / 2
        if is_p:
            svg.append(f'<rect x="{dx-5}" y="{dy-5}" width="10" height="10" rx="2" fill="{colors["fill"]}" opacity="0.6"/>')
        else:
            svg.append(f'<rect x="{dx-4}" y="{dy-6}" width="8" height="12" rx="2" fill="{colors["fill"]}" opacity="0.6"/>')
        svg.append(f'<text x="{pr+8}" y="{yb+BAR_H/2+4}" font-size="11" fill="#555">{esc(label)}</text>')

        nums = [v for _, _, v in segs if isinstance(v, (int, float))]
        mx = max(nums) if nums else 1
        for ts, te, val in segs:
            x1, x2 = tx(ts), tx(te)
            w = max(x2 - x1, 1)
            bf = colors['fill']
            bs = colors['stroke']
            if isinstance(val, (int, float)) and mx > 0:
                fr = max(math.sqrt(val / mx), 0.25 if not is_p else 0.35)
                bl = 0.6 if not is_p else 0.45
                fill = lerp_color(make_light(bf, bl), bf, fr)
                bs2 = lerp_color(make_light(bs, 0.5), bs, fr) if not is_p else bs
            else:
                fill = bf
                bs2 = bs
            op = '0.9' if is_p else '0.85'
            sk = '' if is_p else f' stroke="{bs2}" stroke-width="0.5"'
            svg.append(f'<rect x="{x1:.1f}" y="{yb}" width="{w:.1f}" height="{BAR_H}" rx="3" fill="{fill}" opacity="{op}"{sk}/>')
            vs = f'{val}' if isinstance(val, str) else (f'{int(val)}' if isinstance(val, float) and val == int(val) else f'{val:g}')
            if w > len(vs) * 7 + 4:
                tc = 'white' if is_p else '#444'
                svg.append(f'<text x="{(x1+x2)/2:.1f}" y="{yb+BAR_H/2+4}" font-size="11" fill="{tc}" text-anchor="middle" font-weight="500">{esc(vs)}</text>')
            elif w >= 3 and not is_p and isinstance(val, (int, float)) and val > 0.5:
                svg.append(f'<line x1="{x1:.1f}" y1="{yb}" x2="{x1:.1f}" y2="{yb - 6}" stroke="{bs2}" stroke-width="0.7"/>')
                svg.append(f'<text x="{x1:.1f}" y="{yb - 8}" font-size="9" fill="{bs2}" text-anchor="middle" font-weight="bold">{esc(vs)}</text>')

    if gw_start is not None:
        gw_mid = (gw_start + gw_end) / 2
        gw_mfc = {}
        for ch in mfc_ch:
            lv = 0
            for t, n, v in tl.mfc_events:
                if n == ch and t <= gw_mid:
                    lv = v
            if lv > 0.01:
                gw_mfc[ch] = lv
        gas_parts = [f'{ch} {v:g} sccm' for ch in mfc_ch if ch in gw_mfc for v in [gw_mfc[ch]]]
        gw_pc = {}
        for ch in pc_ch:
            lv = 0
            for t, n, v in tl.pc_events:
                if n == ch and t <= gw_mid:
                    lv = v
            if lv > 0:
                gw_pc[ch] = lv
        gw_rtv = 0
        for t, v in tl.rtv_events:
            if t <= gw_mid:
                gw_rtv = v
        gw_spin = 0
        for t, v in tl.spin_events:
            if t <= gw_mid:
                gw_spin = v
        pp = [f'{ch} = {gw_pc[ch]:g} Torr' for ch in pc_ch if ch in gw_pc]
        if gw_rtv > 0:
            pp.append(f'RTV {gw_rtv:g} Torr')
        if gw_spin > 0:
            pp.append(f'Spin: {gw_spin:g} rpm')

        lines = [(f'Growth window · t={gw_start/60:.0f}–{gw_end/60:.0f} min · {peak_T:.0f}°C plateau', '#a0526a', True)]
        if len(' · '.join(gas_parts)) > 90:
            mid = len(gas_parts) // 2
            lines.append(('Gas chemistry: ' + ' · '.join(gas_parts[:mid]), '#666', False))
            lines.append((' · '.join(gas_parts[mid:]), '#666', False))
        else:
            lines.append(('Gas chemistry: ' + ' · '.join(gas_parts), '#666', False))
        lines.append(('Pressure: ' + ' · '.join(pp), '#666', False))
        if p1_trace:
            p1_gw = [T for t, T in p1_trace if t <= gw_mid]
            if p1_gw:
                lines.append((f'Heater 2 (P1): {p1_gw[-1]:.0f}°C', P1_COLOR, False))
        if p2_trace:
            p2_gw = [T for t, T in p2_trace if t <= gw_mid]
            if p2_gw:
                lines.append((f'Heater 3 (P2): {p2_gw[-1]:.0f}°C', P2_COLOR, False))

        bx, by, bw = pl, summary_top, pr - pl
        bh = 20 + len(lines) * 16 + 10
        svg.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="6" fill="#fff8f0" stroke="{GROWTH_STROKE}" stroke-width="1"/>')
        yc = by + 20
        for txt, col, bold in lines:
            wt = ' font-weight="600"' if bold else ''
            fs = '12' if bold else '10.5'
            svg.append(f'<text x="{bx+15}" y="{yc}" font-size="{fs}" fill="{col}"{wt}>{esc(txt)}</text>')
            yc += 16 if bold else 15

    svg.append('</svg>')
    return '\n'.join(svg), {
        'total_min': total_min, 'peak_T': peak_T,
        'gw_start_min': gw_start / 60 if gw_start else None, 'gw_end_min': gw_end / 60 if gw_end else None,
        'gw_dur': gw_dur, 'p1_T': p1_final, 'p2_T': p2_final, 'canvas_h': canvas_h,
    }

"""Runcard View - visualize a runcard recipe's process profile as an SVG chart.

A standalone page: it only reads from datalog_monitor's shared helpers and
never touches app.py, so it can't regress the existing run browser.
"""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from datalog_monitor import growth_window as gw
from datalog_monitor import runcard as rc
from datalog_monitor import runcard_svg as rsvg
from datalog_monitor import storage
from datalog_monitor.folder_picker import pick_folder_dialog

st.set_page_config(page_title="Runcard View - Datalog Monitor", layout="wide")


def _download_component_html(svg_str: str, run_id: str, canvas_h: float) -> str:
    """Embeds the SVG plus a client-side "Download PNG" button. The PNG is
    rasterized entirely in the browser (SVG -> <canvas> -> toBlob) -- no
    server-side rendering, so no cairosvg / native Cairo library needs
    bundling into the portable Windows build.
    """
    svg_with_id = svg_str.replace('<svg ', '<svg id="chart-svg" ', 1)
    filename = json.dumps(f"{run_id}_runcard.png")
    return f'''
<div style="font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;">
  {svg_with_id}
  <div style="margin-top:8px;">
    <button id="download-btn" style="padding:6px 14px;font-size:13px;cursor:pointer;">Download PNG</button>
  </div>
</div>
<script>
document.getElementById('download-btn').addEventListener('click', function () {{
  var svg = document.getElementById('chart-svg');
  var svgData = new XMLSerializer().serializeToString(svg);
  var svgBlob = new Blob([svgData], {{ type: 'image/svg+xml;charset=utf-8' }});
  var url = URL.createObjectURL(svgBlob);
  var img = new Image();
  img.onload = function () {{
    var scale = 2;
    var canvas = document.createElement('canvas');
    canvas.width = {rsvg.W} * scale;
    canvas.height = {canvas_h} * scale;
    var ctx = canvas.getContext('2d');
    ctx.scale(scale, scale);
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, {rsvg.W}, {canvas_h});
    // Explicit destination size: the source SVG has no width/height (only
    // viewBox), so a detached Image() loaded from a blob URL -- no CSS
    // container to inherit sizing from -- falls back to the default
    // replaced-element size (300x150) rather than the viewBox, and an
    // unsized drawImage(img, 0, 0) would rasterize at that tiny size
    // instead of filling the canvas.
    ctx.drawImage(img, 0, 0, {rsvg.W}, {canvas_h});
    URL.revokeObjectURL(url);
    canvas.toBlob(function (blob) {{
      var link = document.createElement('a');
      link.download = {filename};
      link.href = URL.createObjectURL(blob);
      link.click();
    }});
  }};
  img.src = url;
}});
</script>
'''


def render_runcard_picker(runcard_folder: str, mode: str) -> list[str]:
    paths = rc.list_runcards(runcard_folder)
    st.caption(f"{len(paths)} runcard(s) found in {runcard_folder}")
    if not paths:
        return []

    table_rows = [
        {
            "Runcard": Path(p).stem,
            "Modified": pd.Timestamp(Path(p).stat().st_mtime, unit="s").strftime("%Y-%m-%d %H:%M:%S"),
        }
        for p in paths
    ]
    selection_mode = "single-row" if mode == "Single runcard" else "multi-row"
    event = st.dataframe(
        pd.DataFrame(table_rows), hide_index=True, width="stretch",
        on_select="rerun", selection_mode=selection_mode, key=f"runcard_table_{mode}",
    )
    selected_indices = event.selection.rows if event and event.selection else []
    return [paths[i] for i in selected_indices if i < len(paths)]


def render_chart_panel(path: str) -> None:
    commands = rc.parse_runcard(path)
    profile = gw.build_profile(commands)
    run_id = rsvg.derive_run_id(path)
    svg_str, stats = rsvg.render_svg(run_id, profile)

    st.divider()
    st.subheader(run_id)
    cols = st.columns(5)
    cols[0].metric("Total time", f"{stats['total_min']:.0f} min")
    cols[1].metric("Peak T", f"{stats['peak_T']:.0f}°C" if stats['peak_T'] is not None else "—")
    if stats['gw_start_min'] is not None:
        cols[2].metric("Growth window", f"{stats['gw_start_min']:.0f}–{stats['gw_end_min']:.0f} min")
        cols[3].metric("Growth duration", f"{stats['gw_dur']:.0f} min")
    if stats['p1_T'] is not None:
        cols[4].metric("P1 final", f"{stats['p1_T']:.0f}°C")

    html = _download_component_html(svg_str, run_id, stats['canvas_h'])
    st.components.v1.html(html, height=int(stats['canvas_h']) + 90, scrolling=False)


def main() -> None:
    st.title("Runcard View")
    st.caption("Visualize a runcard recipe's process profile.")

    if "runcard_folder" not in st.session_state:
        st.session_state.runcard_folder = storage.get_runcard_folder() or ""

    st.sidebar.header("Runcard folder")
    st.sidebar.text_input("Current folder", value=st.session_state.runcard_folder, disabled=True)
    if st.sidebar.button("Browse for runcard folder..."):
        folder = pick_folder_dialog(st.session_state.runcard_folder)
        if folder:
            st.session_state.runcard_folder = folder
            storage.set_runcard_folder(folder)
            st.rerun()

    runcard_folder = st.session_state.runcard_folder
    if not runcard_folder:
        st.info("Choose a runcard folder from the sidebar to get started.")
        return

    mode = st.sidebar.radio("View mode", ["Single runcard", "Compare runcards"])

    st.subheader("Runcards")
    selected_paths = render_runcard_picker(runcard_folder, mode)
    if not selected_paths:
        st.info("Select a runcard to view its profile.")
        return

    for path in selected_paths:
        render_chart_panel(path)


main()

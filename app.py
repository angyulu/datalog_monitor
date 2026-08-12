"""Datalog Monitor - local Streamlit viewer for process-log CSV runs."""
import subprocess
from pathlib import Path

import pandas as pd
import streamlit as st

from datalog_monitor import __version__, renamer, storage
from datalog_monitor.analysis import compute_all_violations, compute_summary_stats, find_final_plateau_start
from datalog_monitor.charts import build_comparison_figure, build_single_run_figure
from datalog_monitor.scanner import (
    detect_pv_sv_pairs,
    get_plain_numeric_channels,
    load_run,
    scan_folder,
    ALIGNMENT_SV_COLUMN,
    PRESSURE_GROUP_LABEL_COLUMN,
    PRESSURE_GROUP_NUMERIC,
)

st.set_page_config(page_title="Datalog Monitor", layout="wide")

DEFAULT_CHANNEL_LABELS = {"Tube Pressure", "651C Pre", "Heater"}
RECENT_WINDOW_OPTIONS = {"Last 50 runs": 50, "Last 100 runs": 100, "Last 200 runs": 200, "All runs": None}


def _ps_single_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def pick_folder_dialog(initial_dir: str | None) -> str | None:
    """Native folder picker via PowerShell + WinForms.

    Not tkinter: the Windows embeddable Python distribution used for the
    portable/no-install build doesn't ship tkinter at all, and PowerShell's
    WinForms are present on every Windows machine with no bundling needed.
    """
    initial_dir_literal = _ps_single_quote(initial_dir) if initial_dir else "''"
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'Select the data folder'
$initial = {initial_dir_literal}
if ($initial -and (Test-Path $initial)) {{
    $dialog.SelectedPath = $initial
}}
$dialog.ShowNewFolderButton = $false
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
    Write-Output $dialog.SelectedPath
}}
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            capture_output=True, text=True, timeout=180,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    path = result.stdout.strip()
    return path or None


def build_plot_item_catalog(columns: list[str]) -> list[dict]:
    pv_sv_pairs = detect_pv_sv_pairs(columns)
    plain_channels = get_plain_numeric_channels(columns, pv_sv_pairs)

    catalog = []
    for channel in PRESSURE_GROUP_NUMERIC:
        if channel in plain_channels:
            catalog.append({"kind": "plain", "channel": channel, "label": channel})
    for name, pv, sv in pv_sv_pairs:
        catalog.append({"kind": "pvsv", "pair_name": name, "pv_col": pv, "sv_col": sv, "label": name})
    for channel in plain_channels:
        if channel not in PRESSURE_GROUP_NUMERIC:
            catalog.append({"kind": "plain", "channel": channel, "label": channel})
    return catalog


def format_duration(delta: pd.Timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def render_run_table(root_folder: str, mode: str) -> list[str]:
    """Renders the run list/search/tag-editor and returns the selected file path(s)."""
    runs = scan_folder(root_folder)
    st.caption(f"{len(runs)} run(s) found on disk · auto-refreshes every 60s")
    st.button("Refresh now", key="manual_refresh")

    if not runs:
        st.info("No CSV files found in this folder.")
        return []

    tags = storage.load_runcard_tags(root_folder)
    query = st.text_input("Search (timestamp or runcard)", key="search_query").strip().lower()

    if query:
        # Search always looks across every run, not just the recent window.
        candidate_runs = runs
    else:
        window_label = st.selectbox("Show", list(RECENT_WINDOW_OPTIONS), key="recent_window")
        limit = RECENT_WINDOW_OPTIONS[window_label]
        candidate_runs = runs[:limit] if limit else runs

    table_rows = []
    row_meta = []
    for meta in candidate_runs:
        tag = storage.get_runcard_tag(root_folder, meta.path, tags)
        if query and query not in f"{meta.start_time:%Y-%m-%d %H:%M:%S} {tag}".lower():
            continue
        table_rows.append({
            "Start": meta.start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "Program": meta.first_program,
            "Rows": meta.row_count,
            "Duration": format_duration(meta.end_time - meta.start_time),
            "Runcard": tag,
        })
        row_meta.append(meta)

    st.caption(f"Showing {len(table_rows)} run(s)")
    if not table_rows:
        return []

    selection_mode = "single-row" if mode == "Single run" else "multi-row"
    event = st.dataframe(
        pd.DataFrame(table_rows), hide_index=True, width="stretch",
        on_select="rerun", selection_mode=selection_mode, key=f"run_table_{mode}",
    )
    selected_indices = event.selection.rows if event and event.selection else []
    # A selection can carry over from before the row set shrank (narrowing the
    # search, a smaller "Show" window, or the periodic re-scan finding fewer
    # matching runs) -- st.dataframe's selection is keyed by row position, not
    # by run identity, so a stale index needs to be dropped rather than crash.
    selected_metas = [row_meta[i] for i in selected_indices if i < len(row_meta)]

    if selected_metas:
        st.divider()
        st.caption("Edit runcard tag for the selected run(s):")
        for meta in selected_metas:
            tag = storage.get_runcard_tag(root_folder, meta.path, tags)
            new_tag = st.text_input(
                f"{meta.start_time:%Y-%m-%d %H:%M:%S}", value=tag, key=f"tag_{meta.path}",
            )
            if new_tag != tag:
                storage.set_runcard_tag(root_folder, meta.path, new_tag)

            plan = renamer.plan_single_rename(root_folder, meta)
            if plan.will_change:
                if st.button(f"Rename file to {Path(plan.new_path).name}", key=f"rename_{meta.path}"):
                    try:
                        renamer.apply_rename(root_folder, plan)
                    except (renamer.RenameCollision, OSError) as exc:
                        st.error(str(exc))
                    else:
                        st.success(f"Renamed to {Path(plan.new_path).name}")
                        st.rerun()
            else:
                st.caption("Filename already matches this tag.")

    return [m.path for m in selected_metas]


def render_tolerance_settings(root_folder: str, pv_sv_pairs: list[tuple[str, str, str]]) -> dict:
    thresholds = storage.load_thresholds(root_folder)
    with st.expander("PV/SV tolerance settings"):
        global_default = st.number_input(
            "Global default tolerance (%)", min_value=0.0, step=0.5,
            value=float(thresholds["global_default_pct"]), key="global_tolerance",
        )
        pair_names = [name for name, _, _ in pv_sv_pairs]
        rows = pd.DataFrame({
            "Channel": pair_names,
            "Tolerance %": [
                float(thresholds["overrides"].get(name, global_default)) for name in pair_names
            ],
        })
        edited = st.data_editor(rows, hide_index=True, key="tolerance_editor", width="stretch")
        if st.button("Save tolerance settings"):
            new_overrides = {
                row["Channel"]: row["Tolerance %"]
                for _, row in edited.iterrows()
                if abs(row["Tolerance %"] - global_default) > 1e-9
            }
            storage.save_thresholds(root_folder, {
                "global_default_pct": global_default, "overrides": new_overrides,
            })
            st.rerun()
    return {"global_default_pct": global_default, "overrides": thresholds["overrides"]}


def get_tolerance_pct(thresholds: dict, pair_name: str) -> float:
    return thresholds.get("overrides", {}).get(pair_name, thresholds["global_default_pct"])


def render_single_run_view(df: pd.DataFrame, plot_items: list[dict], pv_sv_pairs, thresholds) -> None:
    pressure_group_selected = any(
        i["kind"] == "plain" and i["channel"] in PRESSURE_GROUP_NUMERIC for i in plot_items
    )
    if pressure_group_selected and PRESSURE_GROUP_LABEL_COLUMN in df.columns:
        gauge_values = df[PRESSURE_GROUP_LABEL_COLUMN].dropna().unique()
        st.caption(f"{PRESSURE_GROUP_LABEL_COLUMN}: {', '.join(str(v) for v in gauge_values)}")

    violations_df, masks = compute_all_violations(df, pv_sv_pairs, thresholds, get_tolerance_pct)
    fig = build_single_run_figure(df, plot_items, masks)
    st.plotly_chart(fig, width="stretch")

    st.subheader("Summary statistics")
    all_channels = [i["pv_col"] for i in plot_items if i["kind"] == "pvsv"] + \
                    [i["sv_col"] for i in plot_items if i["kind"] == "pvsv"] + \
                    [i["channel"] for i in plot_items if i["kind"] == "plain"]
    st.dataframe(compute_summary_stats(df, all_channels), width="stretch", hide_index=True)

    st.subheader("Out-of-tolerance violations")
    if violations_df.empty:
        st.success("No PV/SV violations found for this run.")
    else:
        st.dataframe(violations_df, width="stretch", hide_index=True)


def render_comparison_view(root_folder: str, dfs, plot_items: list[dict], pv_sv_pairs, thresholds) -> None:
    tags = storage.load_runcard_tags(root_folder)
    run_labels = []
    align_times = []
    fallback_labels = []
    for path, df in dfs:
        tag = storage.get_runcard_tag(root_folder, path, tags)
        start = df["Time"].iloc[0]
        label = (f"{tag} " if tag else "") + f"{start:%Y-%m-%d %H:%M:%S}"
        run_labels.append(label)

        align_time = find_final_plateau_start(df, ALIGNMENT_SV_COLUMN) if ALIGNMENT_SV_COLUMN in df.columns else None
        if align_time is None:
            align_time = start
            fallback_labels.append(label)
        align_times.append(align_time)

    if fallback_labels:
        st.warning(
            f"{ALIGNMENT_SV_COLUMN} not available in: {', '.join(fallback_labels)} "
            "-- aligned by run start time instead."
        )

    fig = build_comparison_figure(list(zip(run_labels, [d for _, d in dfs])), plot_items, align_times)
    st.plotly_chart(fig, width="stretch")

    st.subheader("Summary statistics")
    all_channels = [i["pv_col"] for i in plot_items if i["kind"] == "pvsv"] + \
                    [i["sv_col"] for i in plot_items if i["kind"] == "pvsv"] + \
                    [i["channel"] for i in plot_items if i["kind"] == "plain"]
    stats_frames = []
    for run_label, (path, df) in zip(run_labels, dfs):
        stats = compute_summary_stats(df, all_channels)
        stats.insert(0, "Run", run_label)
        stats_frames.append(stats)
    st.dataframe(pd.concat(stats_frames, ignore_index=True), width="stretch", hide_index=True)

    st.subheader("Out-of-tolerance violations")
    violation_frames = []
    for run_label, (path, df) in zip(run_labels, dfs):
        v_df, _ = compute_all_violations(df, pv_sv_pairs, thresholds, get_tolerance_pct)
        if not v_df.empty:
            v_df.insert(0, "Run", run_label)
            violation_frames.append(v_df)
    if violation_frames:
        st.dataframe(pd.concat(violation_frames, ignore_index=True), width="stretch", hide_index=True)
    else:
        st.success("No PV/SV violations found across selected runs.")


@st.fragment(run_every="60s")
def render_workspace(root_folder: str, mode: str) -> None:
    """Run picker + everything downstream of a selection, in one reactive scope.

    Selecting a row is a widget interaction *inside* this fragment, so it must
    also own the chart/stats rendering -- code outside a fragment does not
    re-run when only the fragment reruns (a plain st.button/dataframe click
    inside it would otherwise update session_state with nothing downstream
    ever seeing the new value until some unrelated full-page rerun happened).
    Streamlit also doesn't allow a fragment to write to both the sidebar and
    the main area, so the run table lives here in the main area now.
    """
    st.subheader("Runs")
    selected_paths = render_run_table(root_folder, mode)

    if not selected_paths:
        st.info("Select a run from the sidebar to view its data.")
        return

    dfs = [(path, load_run(path)) for path in selected_paths]
    columns = list(dfs[0][1].columns)
    catalog = build_plot_item_catalog(columns)
    pv_sv_pairs = [(i["pair_name"], i["pv_col"], i["sv_col"]) for i in catalog if i["kind"] == "pvsv"]

    thresholds = render_tolerance_settings(root_folder, pv_sv_pairs)

    labels = [item["label"] for item in catalog]
    default_labels = [label for label in labels if label in DEFAULT_CHANNEL_LABELS]
    selected_labels = st.multiselect("Channels to plot", labels, default=default_labels)
    plot_items = [item for item in catalog if item["label"] in selected_labels]

    if not plot_items:
        st.info("Select at least one channel to plot.")
        return

    if mode == "Single run":
        render_single_run_view(dfs[0][1], plot_items, pv_sv_pairs, thresholds)
    else:
        render_comparison_view(root_folder, dfs, plot_items, pv_sv_pairs, thresholds)


def render_bulk_rename(root_folder: str) -> None:
    """Sidebar control to sweep the whole folder tree, renaming every run to
    <timestamp>[~tag].csv so filenames stay consistent for downstream analysis.

    Recomputes every target name from current data each time, so it also
    fixes files that were renamed earlier but whose tag has since changed.
    """
    st.sidebar.divider()
    st.sidebar.subheader("Bulk rename")
    st.sidebar.caption("Rename every run in this folder (recursively) to match its tag.")

    if st.sidebar.button("Preview rename all"):
        st.session_state.rename_plans = [p for p in renamer.plan_renames(root_folder) if p.will_change]
        st.session_state.rename_result = None

    plans = st.session_state.get("rename_plans")
    if plans is not None:
        if not plans:
            st.sidebar.info("Every filename already matches its tag.")
            st.session_state.rename_plans = None
        else:
            st.sidebar.write(f"{len(plans)} file(s) will change:")
            st.sidebar.dataframe(
                pd.DataFrame([
                    {
                        "Current name": Path(p.path).name,
                        "New name": Path(p.new_path).name,
                        "Status": "Collision - will be skipped" if p.collision else "OK",
                    }
                    for p in plans
                ]),
                hide_index=True, width="stretch",
            )
            col1, col2 = st.sidebar.columns(2)
            if col1.button("Confirm rename all"):
                st.session_state.rename_result = renamer.execute_sweep(root_folder, plans)
                st.session_state.rename_plans = None
                st.rerun()
            if col2.button("Cancel"):
                st.session_state.rename_plans = None
                st.rerun()

    result = st.session_state.get("rename_result")
    if result is not None:
        st.sidebar.success(f"Renamed {len(result.renamed)} file(s).")
        if result.skipped:
            details = "\n".join(f"- {Path(p).name}: {reason}" for p, reason in result.skipped)
            st.sidebar.warning(f"Skipped {len(result.skipped)} file(s):\n{details}")


def main() -> None:
    st.title("Datalog Monitor")
    st.caption(f"v{__version__}")

    if "root_folder" not in st.session_state:
        st.session_state.root_folder = storage.get_last_folder() or ""

    st.sidebar.header("Data folder")
    st.sidebar.text_input("Current folder", value=st.session_state.root_folder, disabled=True)
    if st.sidebar.button("Browse…"):
        folder = pick_folder_dialog(st.session_state.root_folder)
        if folder:
            st.session_state.root_folder = folder
            storage.set_last_folder(folder)
            st.rerun()

    root_folder = st.session_state.root_folder
    if not root_folder:
        st.info("Choose a data folder from the sidebar to get started.")
        return

    render_bulk_rename(root_folder)

    mode = st.sidebar.radio("View mode", ["Single run", "Compare runs"])

    render_workspace(root_folder, mode)


if __name__ == "__main__":
    # Explicit st.Page list rather than relying on the pages/ folder's
    # implicit auto-discovery: that would label this entry "app" in the
    # sidebar (derived straight from the app.py filename), and renaming the
    # file itself would ripple into installer/update_check.ps1's atomic
    # rename-based swap, which is built specifically around the literal
    # filename "app.py". This relabels just the sidebar without touching
    # the on-disk entry point the installer/launcher/updater all depend on.
    st.navigation([
        st.Page(main, title="Datalog", default=True),
        st.Page("pages/1_Runcard_Check.py", title="Runcard Check"),
        st.Page("pages/2_Split_Table.py", title="Split Table"),
        st.Page("pages/3_Runcard_View.py", title="Runcard View"),
    ]).run()

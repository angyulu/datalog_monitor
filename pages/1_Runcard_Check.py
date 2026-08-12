"""Runcard Check - verify a run's datalog matches its paired runcard recipe.

A standalone page: it only reads from datalog_monitor's shared helpers and
never touches app.py, so it can't regress the existing run browser.
"""
from pathlib import Path

import pandas as pd
import streamlit as st

from datalog_monitor import storage
from datalog_monitor.folder_picker import pick_folder_dialog
from datalog_monitor.runcard import parse_runcard
from datalog_monitor.runcard_check import check_run
from datalog_monitor.scanner import load_run, scan_folder

st.set_page_config(page_title="Runcard Check - Datalog Monitor", layout="wide")

STATUS_ICON = {"Pass": "✅", "Fail": "❌", "Incomplete": "⏸️"}


def find_paired_runcard(runcard_folder: str, tag: str) -> str | None:
    if not tag or not runcard_folder:
        return None
    candidate = Path(runcard_folder) / f"{tag}.csv"
    return str(candidate) if candidate.is_file() else None


@st.cache_data(show_spinner=False)
def _cached_check(
    datalog_path: str, _datalog_mtime: float, runcard_path: str, _runcard_mtime: float,
    global_default_pct: float, timing_tolerance_pct: float, timing_floor_sec: float,
    overrides_items: tuple[tuple[str, float], ...],
):
    """`_datalog_mtime`/`_runcard_mtime` are cache-busting keys, not used directly."""
    df = load_run(datalog_path)
    commands = parse_runcard(runcard_path)
    overrides = dict(overrides_items)

    def get_setpoint_tolerance_pct(pair_name: str) -> float:
        return overrides.get(pair_name, global_default_pct)

    return check_run(
        commands, df,
        timing_tolerance_pct=timing_tolerance_pct, timing_floor_sec=timing_floor_sec,
        get_setpoint_tolerance_pct=get_setpoint_tolerance_pct,
    )


def run_check(datalog_path: str, runcard_path: str, thresholds: dict):
    return _cached_check(
        datalog_path, Path(datalog_path).stat().st_mtime,
        runcard_path, Path(runcard_path).stat().st_mtime,
        thresholds["global_default_pct"], thresholds["timing_tolerance_pct"], thresholds["timing_floor_sec"],
        tuple(sorted(thresholds.get("overrides", {}).items())),
    )


def render_timing_settings(root_folder: str, thresholds: dict) -> dict:
    with st.expander("Timing tolerance settings"):
        timing_pct = st.number_input(
            "Wait-duration tolerance (%)", min_value=0.0, step=0.5,
            value=float(thresholds["timing_tolerance_pct"]), key="timing_tolerance_pct",
        )
        timing_floor = st.number_input(
            "Wait-duration tolerance floor (seconds)", min_value=0.0, step=0.5,
            value=float(thresholds["timing_floor_sec"]), key="timing_floor_sec",
        )
        if st.button("Save timing tolerance"):
            thresholds = dict(thresholds)
            thresholds["timing_tolerance_pct"] = timing_pct
            thresholds["timing_floor_sec"] = timing_floor
            storage.save_thresholds(root_folder, thresholds)
            st.rerun()
    return thresholds


def render_result_detail(meta, runcard_path: str, result) -> None:
    st.divider()
    st.subheader(f"{meta.start_time:%Y-%m-%d %H:%M:%S} vs {Path(runcard_path).name}")

    if result.status == "Pass":
        st.success(f"{STATUS_ICON['Pass']} Pass — datalog matches the runcard within tolerance.")
    elif result.status == "Incomplete":
        st.warning(
            f"{STATUS_ICON['Incomplete']} Incomplete — stopped at step "
            f"{result.matched_steps} of {result.total_steps}."
        )
    else:
        st.error(f"{STATUS_ICON['Fail']} Fail — see discrepancies below.")

    if result.sequence_issues:
        st.write("**Sequence discrepancies**")
        st.dataframe(pd.DataFrame([
            {
                "Position": issue.position,
                "Type": issue.kind,
                "Runcard expected": ", ".join(issue.runcard_steps) or "(nothing)",
                "Datalog actual": ", ".join(issue.datalog_steps) or "(nothing)",
            }
            for issue in result.sequence_issues
        ]), hide_index=True, width="stretch")

    if result.timing_issues:
        st.write("**Timing discrepancies**")
        st.dataframe(pd.DataFrame([
            {
                "Step": issue.step_name, "Position": issue.position,
                "Programmed (s)": issue.programmed_sec, "Actual (s)": issue.actual_sec,
                "Start": issue.start_time,
            }
            for issue in result.timing_issues
        ]), hide_index=True, width="stretch")

    if result.setpoint_issues:
        st.write("**Setpoint discrepancies**")
        st.dataframe(pd.DataFrame([
            {
                "Command": issue.command_name, "Column": issue.column,
                "Expected": issue.expected, "Actual": issue.actual, "Checked at": issue.check_time,
            }
            for issue in result.setpoint_issues
        ]), hide_index=True, width="stretch")


def main() -> None:
    st.title("Runcard Check")
    st.caption("Verify each run's datalog matches its paired runcard recipe.")

    if "root_folder" not in st.session_state:
        st.session_state.root_folder = storage.get_last_folder() or ""
    if "runcard_folder" not in st.session_state:
        st.session_state.runcard_folder = storage.get_runcard_folder() or ""

    st.sidebar.header("Folders")
    st.sidebar.text_input("Data folder", value=st.session_state.root_folder, disabled=True)
    st.sidebar.text_input("Runcard folder", value=st.session_state.runcard_folder, disabled=True)
    if st.sidebar.button("Browse for runcard folder…"):
        folder = pick_folder_dialog(st.session_state.runcard_folder)
        if folder:
            st.session_state.runcard_folder = folder
            storage.set_runcard_folder(folder)
            st.rerun()

    root_folder = st.session_state.root_folder
    runcard_folder = st.session_state.runcard_folder
    if not root_folder:
        st.info("Select a data folder on the main Datalog Monitor page first.")
        return
    if not runcard_folder:
        st.info("Choose a runcard folder from the sidebar to get started.")
        return

    thresholds = storage.load_thresholds(root_folder)
    thresholds = render_timing_settings(root_folder, thresholds)

    runs = scan_folder(root_folder)
    tags = storage.load_runcard_tags(root_folder)

    table_rows = []
    row_meta = []
    for meta in runs:
        tag = storage.get_runcard_tag(root_folder, meta.path, tags)
        runcard_path = find_paired_runcard(runcard_folder, tag)
        if runcard_path is None:
            continue
        result = run_check(meta.path, runcard_path, thresholds)
        table_rows.append({
            "Status": f"{STATUS_ICON[result.status]} {result.status}",
            "Start": meta.start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "Runcard": tag,
            "Steps matched": f"{result.matched_steps}/{result.total_steps}",
            "Issues": len(result.sequence_issues) + len(result.timing_issues) + len(result.setpoint_issues),
        })
        row_meta.append((meta, runcard_path, result))

    st.caption(f"{len(table_rows)} run(s) with a matching runcard in {runcard_folder}")
    if not table_rows:
        st.info("No runs found whose runcard tag matches a file in the runcard folder.")
        return

    event = st.dataframe(
        pd.DataFrame(table_rows), hide_index=True, width="stretch",
        on_select="rerun", selection_mode="single-row", key="runcard_check_table",
    )
    selected_indices = event.selection.rows if event and event.selection else []
    if selected_indices:
        meta, runcard_path, result = row_meta[selected_indices[0]]
        render_result_detail(meta, runcard_path, result)


main()

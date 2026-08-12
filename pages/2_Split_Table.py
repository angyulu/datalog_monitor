"""Split Table - one-row-per-runcard summary, computed from each runcard's
own profile (growth window, gas chemistry, pressures, spin, heater temps).

A standalone page: it only reads from datalog_monitor's shared helpers and
never touches app.py, so it can't regress the existing run browser.
"""
from pathlib import Path

import pandas as pd
import streamlit as st

from datalog_monitor import runcard as rc
from datalog_monitor import split_table as split_table_lib
from datalog_monitor import storage
from datalog_monitor.folder_picker import pick_folder_dialog

st.set_page_config(page_title="Split Table - Datalog Monitor", layout="wide")


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


def render_table(selected_paths: list[str]) -> None:
    df = split_table_lib.build_table(selected_paths)
    st.subheader("Split table")
    st.dataframe(df, hide_index=True, width="stretch")


def main() -> None:
    st.title("Split Table")
    st.caption("One row per runcard: growth window, gas chemistry, pressures, spin, heater temps.")

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
        st.info("Select a runcard to view its split-table row.")
        return

    render_table(selected_paths)


main()

"""Plotly figure construction: stacked, linked-x-axis subplots for single-run and comparison views."""
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .scanner import TIME_COLUMN

VIOLATION_COLOR = "#d62728"
RUN_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#9467bd",
    "#8c564b", "#e377c2", "#17becf", "#bcbd22",
]


def _plot_item_label(item: dict) -> str:
    return item["pair_name"] if item["kind"] == "pvsv" else item["channel"]


def build_single_run_figure(df: pd.DataFrame, plot_items: list[dict], violation_masks: dict) -> go.Figure:
    n = len(plot_items)
    fig = make_subplots(
        rows=n, cols=1, shared_xaxes=True,
        subplot_titles=[_plot_item_label(i) for i in plot_items],
        vertical_spacing=min(0.08, 1 / max(n - 1, 1) * 0.5),
    )
    time = df[TIME_COLUMN]
    for row, item in enumerate(plot_items, start=1):
        if item["kind"] == "pvsv":
            pair_name, pv_col, sv_col = item["pair_name"], item["pv_col"], item["sv_col"]
            fig.add_trace(go.Scatter(x=time, y=df[pv_col], name=pv_col, mode="lines",
                                      line=dict(color="#1f77b4"), legendgroup=pair_name,
                                      showlegend=False), row=row, col=1)
            fig.add_trace(go.Scatter(x=time, y=df[sv_col], name=sv_col, mode="lines",
                                      line=dict(color="#ff7f0e", dash="dash"), legendgroup=pair_name,
                                      showlegend=False), row=row, col=1)
            if pair_name in violation_masks:
                mask, _ = violation_masks[pair_name]
                if mask.any():
                    violation_y = df[pv_col].where(mask)
                    fig.add_trace(go.Scatter(x=time, y=violation_y, name=f"{pair_name} out-of-tolerance",
                                              mode="markers", marker=dict(color=VIOLATION_COLOR, size=5),
                                              showlegend=False), row=row, col=1)
        else:
            channel = item["channel"]
            fig.add_trace(go.Scatter(x=time, y=df[channel], name=channel, mode="lines",
                                      line=dict(color="#1f77b4"), showlegend=False), row=row, col=1)
        fig.update_yaxes(title_text=_plot_item_label(item), row=row, col=1)

    fig.update_layout(height=max(220, 220 * n), hovermode="x unified",
                       margin=dict(l=60, r=20, t=40, b=40))
    fig.update_xaxes(title_text="Time", row=n, col=1)
    return fig


def build_comparison_figure(
    runs: list[tuple[str, pd.DataFrame]], plot_items: list[dict], align_times: list[pd.Timestamp],
) -> go.Figure:
    """`align_times[i]` becomes t=0 for `runs[i]` -- e.g. each run's growth-temperature reach point."""
    n = len(plot_items)
    fig = make_subplots(
        rows=n, cols=1, shared_xaxes=True,
        subplot_titles=[_plot_item_label(i) for i in plot_items],
        vertical_spacing=min(0.08, 1 / max(n - 1, 1) * 0.5),
    )
    for run_idx, ((run_label, df), align_time) in enumerate(zip(runs, align_times)):
        color = RUN_COLORS[run_idx % len(RUN_COLORS)]
        elapsed = (df[TIME_COLUMN] - align_time).dt.total_seconds()
        for row, item in enumerate(plot_items, start=1):
            column = item["pv_col"] if item["kind"] == "pvsv" else item["channel"]
            fig.add_trace(
                go.Scatter(x=elapsed, y=df[column], name=run_label, mode="lines",
                           line=dict(color=color), legendgroup=run_label,
                           showlegend=(row == 1)),
                row=row, col=1,
            )
    for row, item in enumerate(plot_items, start=1):
        fig.update_yaxes(title_text=_plot_item_label(item), row=row, col=1)
        fig.add_vline(x=0, row=row, col=1, line_dash="dot", line_color="gray", opacity=0.6)

    fig.update_layout(height=max(220, 220 * n), hovermode="x unified",
                       margin=dict(l=60, r=20, t=40, b=40))
    fig.update_xaxes(title_text="Time relative to growth temperature reached (s)", row=n, col=1)
    return fig

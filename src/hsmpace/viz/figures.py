"""Charts of the tool.

The main diagram follows the shop floor convention: **position on the
horizontal axis**, like the plant layout, and **time on the vertical axis**
increasing downwards. Every piece is drawn as a band between head and tail, so
a collision reads as two bands touching rather than as four lines crossing.
"""

from __future__ import annotations

import plotly.graph_objects as go

from ..core.analysis import GapAnalysis
from ..core.kinematics import interpolated_polyline
from ..core.model import KIND_COILER, KIND_COILBOX, KIND_STAND, UTILITY_WATER, Case
from ..core.simulate import PieceResult
from ..core.studies import MonteCarloResult, PacingPoint
from ..core.tracking import TrackingSeries
from ..core.utilities import UtilityReport

PALETTE = [
    "#1f77b4",
    "#d62728",
    "#2ca02c",
    "#9467bd",
    "#ff7f0e",
    "#17becf",
    "#8c564b",
    "#e377c2",
]

_GRID = "rgba(0,0,0,0.08)"


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _layout(fig: go.Figure, title: str, height: int = 640, top: int = 70) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, y=0.98, yanchor="top"),
        template="plotly_white",
        height=height,
        margin=dict(l=70, r=30, t=top, b=90),
        hovermode="closest",
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="left", x=0),
    )
    fig.update_xaxes(gridcolor=_GRID, zeroline=False)
    fig.update_yaxes(gridcolor=_GRID, zeroline=False)
    return fig


TRACE_POINT_CHOICES = [2, *range(3, 22, 2)]


def space_time_figure(
    case: Case,
    results: list[PieceResult],
    analyses: list[GapAnalysis] | None = None,
    time_down: bool | None = None,
    tracking: list[TrackingSeries] | None = None,
    show_virtual_head: bool = False,
    n_points: int = 2,
) -> go.Figure:
    time_down = case.settings.time_axis_down if time_down is None else time_down
    fig = go.Figure()

    for i, res in enumerate(results):
        color = PALETTE[i % len(PALETTE)]
        t_head, x_head = res.head.polyline()
        t_tail, x_tail = res.tail.polyline()

        fig.add_trace(
            go.Scatter(
                x=x_head + x_tail[::-1],
                y=t_head + t_tail[::-1],
                fill="toself",
                fillcolor=_rgba(color, 0.18),
                line=dict(width=0),
                hoverinfo="skip",
                showlegend=False,
                name=f"{res.piece_id} envelope",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=x_head,
                y=t_head,
                mode="lines",
                line=dict(color=color, width=2),
                name=f"{res.piece_id} head",
                legendgroup=res.piece_id,
                hovertemplate="head %{x:.1f} m<br>t %{y:.1f} s<extra>"
                + res.piece_id
                + "</extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=x_tail,
                y=t_tail,
                mode="lines",
                line=dict(color=color, width=2, dash="dash"),
                name=f"{res.piece_id} tail",
                legendgroup=res.piece_id,
                hovertemplate="tail %{x:.1f} m<br>t %{y:.1f} s<extra>"
                + res.piece_id
                + "</extra>",
            )
        )
        if n_points > 2:
            inner = n_points - 2
            for k in range(1, inner + 1):
                frac = k / (n_points - 1)
                t_m, x_m = interpolated_polyline(res.head, res.tail, frac)
                fig.add_trace(
                    go.Scatter(
                        x=x_m,
                        y=t_m,
                        mode="lines",
                        line=dict(color=color, width=1),
                        opacity=0.45,
                        name=f"{res.piece_id} {k}/{n_points - 1}",
                        legendgroup=res.piece_id,
                        showlegend=False,
                        hovertemplate=(
                            f"point {k}/{n_points - 1} %{{x:.1f}} m<br>t %{{y:.1f}} s"
                            f"<extra>{res.piece_id}</extra>"
                        ),
                    )
                )
        if show_virtual_head:
            t_v, x_v = res.head_virtual.polyline()
            fig.add_trace(
                go.Scatter(
                    x=x_v,
                    y=t_v,
                    mode="lines",
                    line=dict(color=color, width=1, dash="dot"),
                    opacity=0.5,
                    name=f"{res.piece_id} virtual head",
                    legendgroup=res.piece_id,
                    hovertemplate="virtual head %{x:.1f} m<br>t %{y:.1f} s<extra></extra>",
                )
            )

    for series in tracking or []:
        fig.add_trace(
            go.Scatter(
                x=series.head,
                y=series.t,
                mode="markers",
                marker=dict(size=4, color="#444", symbol="circle-open"),
                name=f"{series.piece_id} measured",
                hovertemplate="measured %{x:.1f} m<br>t %{y:.1f} s<extra></extra>",
            )
        )

    t_min = min((r.t_start for r in results), default=0.0)
    t_max = max((r.t_end for r in results), default=1.0)

    # the finishing stands sit a few metres apart: the labels are spread over
    # several tiers so that they do not overlap
    x_span = max(case.line.x_max - case.line.x_min, 1.0)
    min_spacing = 0.025 * x_span
    tier_last: list[float] = []
    tiers: dict[str, int] = {}
    for eq in sorted(case.line.equipment, key=lambda e: e.x):
        level = next(
            (i for i, last in enumerate(tier_last) if eq.x - last >= min_spacing),
            len(tier_last),
        )
        if level == len(tier_last):
            tier_last.append(eq.x)
        else:
            tier_last[level] = eq.x
        tiers[eq.id] = level

    for eq in case.line.equipment:
        is_stand = eq.kind in (KIND_STAND, KIND_COILER, KIND_COILBOX)
        fig.add_shape(
            type="line",
            x0=eq.x,
            x1=eq.x,
            y0=t_min,
            y1=t_max,
            line=dict(
                color="rgba(0,0,0,0.55)" if is_stand else "rgba(0,0,0,0.22)",
                width=1.4 if is_stand else 1,
                dash="solid" if is_stand else "dot",
            ),
            layer="below",
        )
        # labels rotated above the plotting area, so they do not cover the bands
        fig.add_annotation(
            x=eq.x,
            y=1.004 + 0.055 * tiers[eq.id],
            yref="paper",
            text=eq.display,
            textangle=-90,
            showarrow=False,
            xanchor="center",
            yanchor="bottom",
            font=dict(size=9, color="#333" if is_stand else "#8a8a8a"),
        )

    if analyses:
        worst = min(analyses, key=lambda a: a.min_gap)
        if worst.critical:
            fig.add_trace(
                go.Scatter(
                    x=[worst.critical.x],
                    y=[worst.critical.t],
                    mode="markers+text",
                    marker=dict(size=12, color="#d62728", symbol="x"),
                    text=[f" gap {worst.critical.gap:.1f} m"],
                    textposition="middle right",
                    textfont=dict(size=11, color="#d62728"),
                    name="critical point",
                    hovertemplate="minimum gap %{text}<br>x %{x:.1f} m<br>t %{y:.1f} s<extra></extra>",
                )
            )

    _layout(fig, "Space-time diagram", top=170)
    x_lo = min([case.line.x_min] + [min(s.x0 for s in r.tail.segments) for r in results])
    x_hi = max([case.line.x_max] + [max(s.x1 for s in r.head.segments) for r in results])
    span = max(x_hi - x_lo, 1.0)
    fig.update_xaxes(
        title="Position along the line [m]", range=[x_lo - 0.03 * span, x_hi + 0.03 * span]
    )
    fig.update_yaxes(title="Time [s]", autorange="reversed" if time_down else True)
    return fig


def gap_figure(analyses: list[GapAnalysis], gap_min: float) -> go.Figure:
    fig = go.Figure()
    if not analyses:
        fig.add_annotation(
            text="The pieces are never on the line at the same time: no gap to evaluate.",
            showarrow=False,
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
        )
        return _layout(fig, "Gap between consecutive pieces", height=420)

    y_values = [gap_min]
    for i, a in enumerate(analyses):
        color = PALETTE[i % len(PALETTE)]
        t, gap = a.series.polyline()
        y_values.extend(gap)
        fig.add_trace(
            go.Scatter(
                x=t,
                y=gap,
                mode="lines",
                line=dict(color=color, width=2),
                name=f"{a.front_id} / {a.rear_id}",
                hovertemplate="t %{x:.1f} s<br>gap %{y:.1f} m<extra></extra>",
            )
        )
        if a.critical:
            y_values.append(a.critical.gap)
            fig.add_trace(
                go.Scatter(
                    x=[a.critical.t],
                    y=[a.critical.gap],
                    mode="markers",
                    marker=dict(size=9, color=color),
                    showlegend=False,
                    hovertemplate=f"minimum {a.critical.gap:.1f} m at x={a.critical.x:.1f} m<extra></extra>",
                )
            )

    y_lo = min(y_values)
    y_hi = max(y_values)
    span = max(y_hi - y_lo, gap_min, 1.0)
    pad = 0.08 * span
    axis_lo = min(y_lo, 0.0) - pad
    axis_hi = y_hi + pad

    fig.add_hrect(
        y0=axis_lo,
        y1=gap_min,
        fillcolor="rgba(214,39,40,0.06)",
        line_width=0,
        layer="below",
    )
    fig.add_hline(
        y=gap_min,
        line=dict(color="#d62728", width=1.5, dash="dash"),
        annotation_text=f"minimum gap {gap_min:g} m",
        annotation_position="top left",
    )

    _layout(fig, "Gap between pieces on the line", height=420)
    fig.update_xaxes(title="Time [s]")
    fig.update_yaxes(title="Tail to head distance [m]", range=[axis_lo, axis_hi])
    return fig


def pacing_curve_figure(
    curve: list[PacingPoint],
    gap_min: float,
    current_pacing: float | None = None,
    min_pacing: PacingPoint | None = None,
) -> go.Figure:
    fig = go.Figure()
    finite = [p for p in curve if p.min_gap != float("inf")]
    fig.add_trace(
        go.Scatter(
            x=[p.pacing for p in finite],
            y=[p.min_gap for p in finite],
            mode="lines",
            line=dict(color="#1f77b4", width=2.5),
            name="minimum gap",
            customdata=[[p.section or "-", p.x_critical or 0.0] for p in finite],
            hovertemplate="pacing %{x:.1f} s<br>minimum gap %{y:.1f} m"
            "<br>%{customdata[0]} a x=%{customdata[1]:.0f} m<extra></extra>",
        )
    )
    fig.add_hline(
        y=gap_min,
        line=dict(color="#d62728", width=1.5, dash="dash"),
        annotation_text=f"minimum gap required {gap_min:g} m",
        annotation_position="bottom right",
    )
    if min_pacing is not None:
        fig.add_vline(
            x=min_pacing.pacing,
            line=dict(color="#2ca02c", width=1.5, dash="dot"),
            annotation_text=f"minimum pacing {min_pacing.pacing:.1f} s",
            annotation_position="top left",
        )
    if current_pacing is not None:
        fig.add_vline(
            x=current_pacing,
            line=dict(color="#333", width=1.2),
            annotation_text=f"current pacing {current_pacing:.0f} s",
            annotation_position="top right",
        )

    _layout(fig, "Minimum gap versus pacing", height=460)
    fig.update_xaxes(title="Pacing [s]")
    fig.update_yaxes(title="Minimum gap of the sequence [m]")
    return fig


def gantt_figure(case: Case, results: list[PieceResult]) -> go.Figure:
    fig = go.Figure()
    occupied = {o.equipment_id for res in results for o in res.occupancy}
    order = [
        e.id
        for e in sorted(case.line.equipment, key=lambda e: -e.x)
        if e.id in occupied
    ]
    labels = {e.id: e.display for e in case.line.equipment}

    for i, res in enumerate(results):
        color = PALETTE[i % len(PALETTE)]
        occ = [o for o in res.occupancy if o.equipment_id in occupied]
        fig.add_trace(
            go.Bar(
                x=[o.duration for o in occ],
                y=[labels.get(o.equipment_id, o.equipment_id) for o in occ],
                base=[o.t_in for o in occ],
                orientation="h",
                marker=dict(color=color, line=dict(width=0)),
                name=res.piece_id,
                customdata=[[o.pass_no, o.t_in, o.t_out] for o in occ],
                hovertemplate="pass %{customdata[0]}<br>%{y}"
                "<br>from %{customdata[1]:.1f} s to %{customdata[2]:.1f} s<extra>"
                + res.piece_id
                + "</extra>",
            )
        )

    _layout(fig, "Occupancy", height=max(420, 28 * max(len(order), 1) + 160))
    fig.update_layout(barmode="overlay", bargap=0.35)
    fig.update_xaxes(title="Time [s]")
    fig.update_yaxes(
        title="", categoryorder="array", categoryarray=[labels.get(i, i) for i in order]
    )
    return fig


def monte_carlo_figure(mc: MonteCarloResult, gap_min: float) -> go.Figure:
    fig = go.Figure()
    finite = [g for g in mc.min_gaps if g != float("inf")]
    if not finite:
        fig.add_annotation(
            text="No interaction between pieces in any run.",
            showarrow=False,
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
        )
        return _layout(fig, "Robustness", height=420)

    fig.add_trace(
        go.Histogram(
            x=finite,
            nbinsx=40,
            marker=dict(color="#1f77b4"),
            name="minimum gap per run",
            hovertemplate="gap %{x:.1f} m<br>%{y} runs<extra></extra>",
        )
    )
    fig.add_vline(
        x=gap_min,
        line=dict(color="#d62728", width=1.5, dash="dash"),
        annotation_text=f"threshold {gap_min:g} m",
        annotation_position="top right",
    )
    _layout(
        fig,
        f"Robustness over {mc.runs} runs: violations {100 * mc.violation_rate:.1f}%",
        height=420,
    )
    fig.update_xaxes(title="Minimum gap of the sequence [m]")
    fig.update_yaxes(title="Number of runs")
    return fig


def utility_rate_figure(report: UtilityReport, utility: str) -> go.Figure:
    """Piecewise-constant instantaneous rate of one utility over the sequence."""
    series = report.water_series if utility == UTILITY_WATER else report.power_series
    ylabel = "Water [L/s]" if utility == UTILITY_WATER else "Power [kW]"
    title = (
        "Instantaneous water"
        if utility == UTILITY_WATER
        else "Instantaneous electrical power"
    )
    fig = go.Figure()
    if not series:
        fig.add_annotation(
            text="No consumption of this utility in the sequence.",
            showarrow=False,
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
        )
        return _layout(fig, title, height=320)
    fig.add_trace(
        go.Scatter(
            x=[p.t for p in series],
            y=[p.rate for p in series],
            mode="lines",
            line=dict(shape="hv", width=2, color="#1f77b4"),
            name=ylabel,
            hovertemplate="t %{x:.1f} s<br>%{y:.1f}<extra></extra>",
        )
    )
    _layout(fig, title, height=320)
    fig.update_xaxes(title="Time [s]")
    fig.update_yaxes(title=ylabel)
    return fig

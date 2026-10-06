"""Checks on the Plotly figures, including axis scaling."""

from __future__ import annotations

import pytest

from hsmpace.core.analysis import analyse_sequence
from hsmpace.core.kinematics import Segment, Trajectory
from hsmpace.core.model import harmonise_tandem_speeds
from hsmpace.core.simulate import PieceResult
from hsmpace.core.studies import base_results, sequence
from hsmpace.example import example_case
from hsmpace.core.utilities import UtilityReport, analyse_utilities
from hsmpace.viz.figures import (
    TRACE_POINT_CHOICES,
    gantt_figure,
    gap_figure,
    space_time_figure,
    utility_rate_figure,
)


def test_the_gap_chart_y_axis_follows_the_data_not_a_million_metres():
    """A violation band from y=-1e6 used to squash every curve onto the zero line."""
    case, _ = harmonise_tandem_speeds(example_case())
    results = sequence(case, base_results(case), case.settings.pacing)
    analyses = analyse_sequence(results, case.settings.gap_min, case.line)
    assert analyses

    fig = gap_figure(analyses, case.settings.gap_min)
    y_lo, y_hi = fig.layout.yaxis.range
    assert y_lo > -50
    assert y_hi < 5_000
    assert y_hi - y_lo > 10

    mins = [a.min_gap for a in analyses]
    assert y_lo < min(mins)
    assert y_hi > max(mins)


def test_the_gantt_includes_occupied_markers():
    case, _ = harmonise_tandem_speeds(example_case())
    results = sequence(case, base_results(case), case.settings.pacing)
    fig = gantt_figure(case, results)
    labels = set()
    for trace in fig.data:
        labels.update(trace.y)
    assert any("Primary descaler" in str(v) for v in labels)
    assert fig.layout.title.text == "Occupancy"


def test_extra_material_points_add_traces():
    case, _ = harmonise_tandem_speeds(example_case())
    results = sequence(case, base_results(case), case.settings.pacing)
    fig2 = space_time_figure(case, results, n_points=2)
    fig5 = space_time_figure(case, results, n_points=5)
    assert TRACE_POINT_CHOICES[0] == 2
    assert 21 in TRACE_POINT_CHOICES
    assert len(fig5.data) > len(fig2.data)


def test_material_points_in_a_15_point_figure_reach_the_coiler_at_strip_speed():
    case, _ = harmonise_tandem_speeds(example_case())
    head_virtual = Trajectory([Segment(0.0, 15.0, 100.0, 10.0, 0.0)])
    tail_virtual = Trajectory([Segment(0.0, 15.0, 0.0, 10.0, 0.0)])
    result = PieceResult(
        piece_id="P1",
        product_id="P",
        t_release=0.0,
        head=head_virtual.clamp_max(120.0),
        tail=tail_virtual.clamp_max(120.0),
        head_virtual=head_virtual,
        x_coiler=120.0,
        coiler_id="DC1",
    )

    fig = space_time_figure(case, [result], n_points=15)

    midpoint = next(trace for trace in fig.data if trace.name == "P1 7/14")
    first_coiler_time = next(
        t for t, x in zip(midpoint.y, midpoint.x) if x == pytest.approx(120.0)
    )
    assert first_coiler_time == pytest.approx(7.0)
    assert max(midpoint.x) <= 120.0


def test_utility_rate_figure_plots_the_step_series():
    case, _ = harmonise_tandem_speeds(example_case())
    results = sequence(case, base_results(case), case.settings.pacing)
    usage = analyse_utilities(case, results)
    assert not usage.empty

    water = utility_rate_figure(usage, "water")
    power = utility_rate_figure(usage, "power")
    assert water.data
    assert power.data
    assert water.layout.yaxis.title.text == "Water [m³/h]"
    assert power.layout.yaxis.title.text == "Power [kW]"
    assert water.data[0].line.shape == "hv"

    empty = utility_rate_figure(UtilityReport((), (), (), 0.0, 0.0), "water")
    assert empty.layout.annotations
    assert "No consumption" in empty.layout.annotations[0].text


def test_blocked_coiler_bars_are_translucent_with_passaggio_hover():
    case, _ = harmonise_tandem_speeds(example_case())
    results = sequence(case, base_results(case), case.settings.pacing)
    fig = gantt_figure(case, results)

    found_passaggio = False
    found_avvolgimento = False
    blocked_colors: list[str] = []
    working_colors: list[str] = []
    for trace in fig.data:
        hover = list(trace.hovertext or [])
        if any("passaggio (mandrino non assegnato)" in str(h) for h in hover):
            found_passaggio = True
            blocked_colors.append(str(trace.marker.color))
        if any("avvolgimento" in str(h) for h in hover):
            found_avvolgimento = True
            working_colors.append(str(trace.marker.color))

    assert found_passaggio
    assert found_avvolgimento
    assert any("0.4" in c and "rgba" in c for c in blocked_colors)
    assert working_colors
    assert all("0.4" not in c for c in working_colors)

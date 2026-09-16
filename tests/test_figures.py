"""Checks on the Plotly figures, including axis scaling."""

from __future__ import annotations

from hsmpace.core.analysis import analyse_sequence
from hsmpace.core.model import harmonise_tandem_speeds
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


def test_utility_rate_figure_plots_the_step_series():
    case, _ = harmonise_tandem_speeds(example_case())
    results = sequence(case, base_results(case), case.settings.pacing)
    usage = analyse_utilities(case, results)
    assert not usage.empty

    water = utility_rate_figure(usage, "water")
    power = utility_rate_figure(usage, "power")
    assert water.data
    assert power.data
    assert water.layout.yaxis.title.text == "Water [L/s]"
    assert power.layout.yaxis.title.text == "Power [kW]"
    assert water.data[0].line.shape == "hv"

    empty = utility_rate_figure(UtilityReport((), (), (), 0.0, 0.0), "water")
    assert empty.layout.annotations
    assert "No consumption" in empty.layout.annotations[0].text

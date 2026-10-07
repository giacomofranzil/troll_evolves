"""Checks of the kinematic engine against cases with a known analytic solution."""

from __future__ import annotations

import math

import pytest

from hsmpace.core.kinematics import (
    QuadPiece,
    Segment,
    Trajectory,
    coilbox_material_trajectory,
    interpolated_polyline,
    interpolated_trajectory,
    overlap_intervals,
    solve_crossing,
    subtract,
)


def test_uniformly_accelerated_segment():
    seg = Segment(t0=2.0, t1=6.0, x0=10.0, v0=3.0, a=2.0)
    # x(6) = 10 + 3*4 + 0.5*2*16 = 38
    assert seg.x_at(6.0) == 38.0
    assert seg.v_at(6.0) == 11.0
    assert seg.x1 == 38.0


def test_crossing_takes_the_first_useful_root():
    # x(t) = 0 + 10 t - 0.5 * 2 * t^2, reaches 21 on the way up at t = 3
    t = solve_crossing(0.0, 0.0, 10.0, -2.0, 21.0, 0.0, 20.0)
    assert t is not None and math.isclose(t, 3.0, abs_tol=1e-9)


def test_crossing_filters_the_direction():
    # a parabola going up and back down crosses x=16 twice
    going_up = solve_crossing(0.0, 0.0, 10.0, -2.0, 16.0, 0.0, 20.0, direction=1)
    coming_down = solve_crossing(0.0, 0.0, 10.0, -2.0, 16.0, 0.0, 20.0, direction=-1)
    assert math.isclose(going_up, 2.0, abs_tol=1e-9)
    assert math.isclose(coming_down, 8.0, abs_tol=1e-9)


def test_trajectory_is_continuous_and_evaluable():
    traj = Trajectory(
        [
            Segment(0.0, 4.0, 0.0, 0.0, 1.0),
            Segment(4.0, 10.0, 8.0, 4.0, 0.0),
        ]
    )
    assert traj.x_at(4.0) == 8.0
    assert traj.x_at(10.0) == 32.0
    assert traj.v_at(2.0) == 2.0


def test_clamping_at_the_coiler_pins_the_head():
    traj = Trajectory([Segment(0.0, 10.0, 0.0, 5.0, 0.0)])
    clamped = traj.clamp_max(20.0)
    assert math.isclose(clamped.x_at(4.0), 20.0)
    assert math.isclose(clamped.x_at(10.0), 20.0)
    assert math.isclose(clamped.x_at(3.0), 15.0)


def test_difference_of_trajectories_is_piecewise_quadratic():
    a = Trajectory([Segment(0.0, 10.0, 100.0, 2.0, 0.0)])
    b = Trajectory([Segment(0.0, 10.0, 0.0, 0.0, 2.0)])
    gap = subtract(a, b, 0.0, 10.0)
    # gap(t) = 100 + 2t - t^2, minimum at the far end: at t=10 it is 20
    t_min, value = gap.minimum()
    assert math.isclose(t_min, 10.0, abs_tol=1e-9)
    assert math.isclose(value, 20.0, abs_tol=1e-9)
    assert math.isclose(gap.value_at(0.0), 100.0)


def test_first_drop_below_threshold_is_exact():
    # gap(t) = 50 - 5t drops below 20 exactly at t = 6
    a = Trajectory([Segment(0.0, 20.0, 50.0, 0.0, 0.0)])
    b = Trajectory([Segment(0.0, 20.0, 0.0, 5.0, 0.0)])
    gap = subtract(a, b, 0.0, 20.0)
    t = gap.first_crossing_below(20.0)
    assert t is not None and math.isclose(t, 6.0, abs_tol=1e-9)


def test_minimum_at_the_vertex_of_the_parabola():
    piece = QuadPiece(t0=0.0, t1=10.0, c0=10.0, c1=-4.0, c2=0.5)
    t, value = piece.minimum()
    assert math.isclose(t, 4.0, abs_tol=1e-9)
    assert math.isclose(value, 2.0, abs_tol=1e-9)


def test_polyline_does_not_subdivide_straight_stretches():
    traj = Trajectory([Segment(0.0, 100.0, 0.0, 1.0, 0.0)])
    ts, xs = traj.polyline()
    assert len(ts) == 2
    assert xs == [0.0, 100.0]


def test_shift_moves_time_only():
    traj = Trajectory([Segment(0.0, 5.0, 3.0, 2.0, 0.0)])
    moved = traj.shift(100.0)
    assert moved.t_start == 100.0
    assert moved.x_at(102.0) == traj.x_at(2.0)


def test_overlap_intervals_finds_two_visits_on_a_reversing_bar():
    # head 0→100 then 100→0; tail 20 m behind. Device at x=40, width 0.
    head = Trajectory(
        [Segment(0.0, 10.0, 0.0, 10.0, 0.0), Segment(10.0, 20.0, 100.0, -10.0, 0.0)]
    )
    tail = Trajectory(
        [Segment(0.0, 10.0, -20.0, 10.0, 0.0), Segment(10.0, 20.0, 80.0, -10.0, 0.0)]
    )
    spans = overlap_intervals(head, tail, 40.0, 40.0)
    assert len(spans) == 2
    assert spans[0][0] == pytest.approx(4.0)
    assert spans[0][1] == pytest.approx(6.0)
    assert spans[1][0] == pytest.approx(14.0)
    assert spans[1][1] == pytest.approx(16.0)


def test_interpolated_polyline_is_the_geometric_fraction():
    head = Trajectory([Segment(0.0, 10.0, 20.0, 2.0, 0.0)])
    tail = Trajectory([Segment(0.0, 10.0, 0.0, 1.0, 0.0)])
    t, x = interpolated_polyline(head, tail, 0.25)
    assert x[0] == pytest.approx(5.0)
    assert x[-1] == pytest.approx(0.25 * head.x_at(10.0) + 0.75 * tail.x_at(10.0))


def test_material_point_keeps_strip_speed_until_it_reaches_the_coiler():
    head_virtual = Trajectory([Segment(0.0, 15.0, 100.0, 10.0, 0.0)])
    tail = Trajectory([Segment(0.0, 15.0, 0.0, 10.0, 0.0)])

    point = interpolated_trajectory(head_virtual, tail, 0.5).clamp_max(120.0)

    assert point.x_at(5.0) == pytest.approx(100.0)
    assert point.v_at(5.0) == pytest.approx(10.0)
    assert point.x_at(7.0) == pytest.approx(120.0)
    assert point.x_at(10.0) == pytest.approx(120.0)
    assert point.v_at(10.0) == pytest.approx(0.0)


def _coilbox_material_point() -> Trajectory:
    head = Trajectory(
        [
            Segment(0.0, 2.0, 80.0, 10.0),
            Segment(2.0, 14.0, 100.0, 0.0),
            Segment(14.0, 30.0, 100.0, 10.0),
        ]
    )
    tail = Trajectory(
        [
            Segment(0.0, 12.0, -20.0, 10.0),
            Segment(12.0, 24.0, 100.0, 0.0),
            Segment(24.0, 30.0, 100.0, 10.0),
        ]
    )
    inbound_head = Trajectory([Segment(2.0, 12.0, 100.0, 10.0)])
    outbound_tail = Trajectory([Segment(14.0, 24.0, 0.0, 10.0)])
    return coilbox_material_trajectory(
        head, tail, inbound_head, outbound_tail, 100.0, 0.5
    )


def test_material_point_keeps_strip_speed_until_absorbed_by_the_coilbox():
    point = _coilbox_material_point()

    assert point.x_at(6.0) == pytest.approx(90.0)
    assert point.v_at(6.0) == pytest.approx(10.0)
    assert point.x_at(8.0) == pytest.approx(100.0)
    assert point.v_at(8.0) == pytest.approx(0.0)


def test_material_point_stays_pinned_then_leaves_the_coilbox_at_strip_speed():
    point = _coilbox_material_point()

    assert point.x_at(16.0) == pytest.approx(100.0)
    assert point.v_at(16.0) == pytest.approx(0.0)
    assert point.x_at(20.0) == pytest.approx(110.0)
    assert point.v_at(20.0) == pytest.approx(10.0)


def test_clamp_max_window_only_caps_inside_the_window():
    traj = Trajectory([Segment(0.0, 10.0, 0.0, 10.0, 0.0)])
    capped = traj.clamp_max_window(40.0, 3.0, 6.0)
    assert capped.x_at(2.0) == pytest.approx(20.0)
    assert capped.x_at(5.0) == pytest.approx(40.0)
    assert capped.x_at(8.0) == pytest.approx(80.0)

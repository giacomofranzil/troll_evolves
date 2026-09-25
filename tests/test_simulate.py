"""Checks of the simulator: kinematics, mass balance, reversals, zoom."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from hsmpace.core.model import (
    FWD,
    REV,
    MAX_COILERS,
    Case,
    Equipment,
    Line,
    ModelError,
    Product,
    RollingPass,
    Section,
    SimSettings,
    SpeedEvent,
    harmonise_tandem_speeds,
    validate_case,
)
from hsmpace.core.simulate import (
    coiler_tail_waypoint,
    simulate_case,
    simulate_piece,
    tail_arrival_speed,
)
from hsmpace.core.studies import base_results, sequence


def _line(stands: list[tuple[str, float]], coiler_x: float = 200.0, v_start: float = 2.0) -> Line:
    equipment = [Equipment("ST", "start", 0.0, accel=1.0)]
    equipment += [Equipment(name, "stand", x, accel=1.0) for name, x in stands]
    equipment.append(Equipment("DC", "coiler", coiler_x, accel=1.0))
    section = Section(
        "S1",
        x_start=0.0,
        length=coiler_x,
        events=(SpeedEvent("S1-1", "S1", x_trigger=0.0, v_target=v_start, direction=FWD),),
    )
    return Line(tuple(equipment), (section,))


def _case(line: Line, passes: list[RollingPass], slab_len: float = 10.0) -> Case:
    product = Product(
        id="P", slab_thk=100.0, slab_wid=1000.0, slab_len=slab_len, passes=tuple(passes)
    )
    return Case(line=line, products=(product,), settings=SimSettings(n_pieces=2))


def _pass(no: int, stand: str, direction: int, h_in: float, h_out: float, v_exit: float, **kw):
    return RollingPass(
        product_id="P",
        pass_no=no,
        equipment_id=stand,
        direction=direction,
        h_in=h_in,
        h_out=h_out,
        w_in=1000.0,
        w_out=1000.0,
        v_exit=v_exit,
        **kw,
    )


def test_single_pass_exact_timings():
    """Hand computed case: ramp 0 to 2 m/s, run to the stand, roll, then coil."""
    case = _case(_line([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)])
    res = simulate_piece(case, case.products[0])

    bite = next(e for e in res.events if e.kind == "bite")
    tail_out = next(e for e in res.events if e.kind == "tail_out")
    # 2 s of ramp at 1 m/s2 cover 2 m, the remaining 48 m at 2 m/s
    assert math.isclose(bite.t, 26.0, abs_tol=1e-6)
    # lambda = 2, so the tail moves at 2 m/s and takes 5 s to clear the stand
    assert math.isclose(tail_out.t, 31.0, abs_tol=1e-6)
    assert math.isclose(res.head.x_at(31.0), 70.0, abs_tol=1e-6)
    assert math.isclose(res.tail.x_at(31.0), 50.0, abs_tol=1e-6)
    # the tail then runs to the coiler slowing down to the final speed: braking from
    # 4 to 1 m/s at 1 m/s2 takes 7.5 m, so 142.5 m at 4 m/s plus 3 s of deceleration
    assert math.isclose(res.t_end, 69.625, abs_tol=1e-6)
    assert res.tail.v_at(res.t_end) == pytest.approx(1.0, abs=1e-6)


def test_mass_balance_is_exact():
    case = _case(_line([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)])
    res = simulate_piece(case, case.products[0])
    assert math.isclose(res.length_geometric, 20.0, abs_tol=1e-9)
    assert math.isclose(res.length_kinematic, 20.0, abs_tol=1e-6)
    assert abs(res.length_error) < 1e-6
    assert res.warnings == ()


def test_the_tail_is_slower_than_the_head_only_while_rolling():
    case = _case(_line([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)])
    res = simulate_piece(case, case.products[0])

    # while rolling: head 4 m/s, tail 2 m/s
    assert math.isclose(res.head.v_at(28.0), 4.0, abs_tol=1e-9)
    assert math.isclose(res.tail.v_at(28.0), 2.0, abs_tol=1e-9)
    # after tail-out the piece is rigid
    assert math.isclose(res.head.v_at(40.0), res.tail.v_at(40.0), abs_tol=1e-9)


def test_mass_flow_chain_in_the_tandem():
    line = _line([("F1", 50.0), ("F2", 60.0)], coiler_x=300.0)
    case = _case(
        line,
        [
            _pass(1, "F1", FWD, 100.0, 50.0, 4.0),
            _pass(2, "F2", FWD, 50.0, 25.0, 8.0),
        ],
    )
    res = simulate_piece(case, case.products[0])
    bites = [e for e in res.events if e.kind == "bite"]
    assert len(bites) == 2

    t = 0.5 * (bites[1].t + min(e.t for e in res.events if e.kind == "tail_out"))
    # with two stands engaged the overall lambda is 4
    assert math.isclose(res.head.v_at(t) / res.tail.v_at(t), 4.0, rel_tol=1e-9)
    assert math.isclose(res.length_geometric, 40.0, abs_tol=1e-9)
    assert math.isclose(res.length_kinematic, 40.0, abs_tol=1e-6)


def test_the_reversal_honours_the_reversing_delay():
    line = _line([("R", 80.0)], coiler_x=400.0)
    case = _case(
        line,
        [
            _pass(1, "R", FWD, 100.0, 80.0, 3.0, reversing_delay=7.0),
            _pass(2, "R", REV, 80.0, 60.0, 3.0, reversing_delay=7.0),
            _pass(3, "R", FWD, 60.0, 40.0, 3.0),
        ],
    )
    res = simulate_piece(case, case.products[0])

    kinds = [e.kind for e in res.events]
    assert kinds.count("bite") == 3
    assert kinds.count("reverse_start") == 2

    wait = next(e for e in res.events if e.kind == "reverse_wait")
    resume = next(e for e in res.events if e.kind == "reverse_end")
    assert math.isclose(resume.t - wait.t, 7.0, abs_tol=1e-6)

    # the piece stands still while waiting
    assert math.isclose(res.head.v_at(0.5 * (wait.t + resume.t)), 0.0, abs_tol=1e-9)


def test_the_reversing_clearance_is_honoured():
    """The piece stops with its closest extremity at the requested distance."""
    line = _line([("R", 80.0)], coiler_x=400.0)
    case = _case(
        line,
        [
            _pass(1, "R", FWD, 100.0, 80.0, 3.0, reversing_delay=4.0, reversing_clearance=12.0),
            _pass(2, "R", REV, 80.0, 60.0, 3.0, reversing_delay=4.0, reversing_clearance=12.0),
            _pass(3, "R", FWD, 60.0, 40.0, 3.0),
        ],
    )
    res = simulate_piece(case, case.products[0])
    assert res.warnings == ()

    wait = next(e for e in res.events if e.kind == "reverse_wait")
    # after a direct pass the extremity closest to the stand is the tail
    assert res.tail.x_at(wait.t) == pytest.approx(92.0, abs=1e-6)

    # after the reverse pass the piece sits upstream: the closest one is the head
    second = [e for e in res.events if e.kind == "reverse_wait"][1]
    assert res.head.x_at(second.t) == pytest.approx(68.0, abs=1e-6)


def test_an_unreachable_clearance_slows_the_mill_to_v_star():
    """Braking at 1 m/s2 from 3 m/s needs 4.5 m; C = 2 m so v* = 2 m/s at tail-out."""
    line = _line([("R", 80.0)], coiler_x=400.0)
    case = _case(
        line,
        [
            _pass(1, "R", FWD, 100.0, 80.0, 3.0, reversing_delay=4.0, reversing_clearance=2.0),
            _pass(2, "R", REV, 80.0, 60.0, 3.0, reversing_delay=4.0, reversing_clearance=2.0),
            _pass(3, "R", FWD, 60.0, 40.0, 3.0),
        ],
    )
    res = simulate_piece(case, case.products[0])
    assert res.warnings == ()
    slow = next(e for e in res.events if e.kind == "reverse_slowdown")
    assert "v* 2.00" in slow.detail
    wait = next(e for e in res.events if e.kind == "reverse_wait")
    assert res.tail.x_at(wait.t) == pytest.approx(82.0, abs=1e-5)
    tail_out = next(e for e in res.events if e.kind == "tail_out")
    assert "v* 2.00" in tail_out.detail
    assert res.tail.v_at(tail_out.t) == pytest.approx(2.0, abs=1e-3)


def test_without_clearance_the_stop_is_at_the_braking_distance():
    line = _line([("R", 80.0)], coiler_x=400.0)
    case = _case(
        line,
        [
            _pass(1, "R", FWD, 100.0, 80.0, 3.0, reversing_delay=4.0),
            _pass(2, "R", REV, 80.0, 60.0, 3.0, reversing_delay=4.0),
            _pass(3, "R", FWD, 60.0, 40.0, 3.0),
        ],
    )
    res = simulate_piece(case, case.products[0])
    wait = next(e for e in res.events if e.kind == "reverse_wait")
    assert res.tail.x_at(wait.t) == pytest.approx(84.5, abs=1e-6)
    assert res.warnings == ()


def test_on_a_reverse_pass_the_piece_travels_back():
    line = _line([("R", 80.0)], coiler_x=400.0)
    case = _case(
        line,
        [
            _pass(1, "R", FWD, 100.0, 80.0, 3.0, reversing_delay=5.0),
            _pass(2, "R", REV, 80.0, 60.0, 3.0, reversing_delay=5.0),
            _pass(3, "R", FWD, 60.0, 40.0, 3.0),
        ],
    )
    res = simulate_piece(case, case.products[0])
    second_bite = [e for e in res.events if e.kind == "bite"][1]
    third_bite = [e for e in res.events if e.kind == "bite"][2]

    # between the second and third bite the piece sits upstream of the stand
    t_mid = 0.5 * (second_bite.t + third_bite.t)
    assert res.tail.x_at(t_mid) < 80.0
    # the head still is the extremity furthest downstream
    assert res.head.x_at(t_mid) >= res.tail.x_at(t_mid) - 1e-9


def test_head_pinned_at_the_coiler_and_virtual_head_free():
    case = _case(_line([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)])
    res = simulate_piece(case, case.products[0])
    assert res.x_coiler == 200.0
    assert max(s.x1 for s in res.head.segments) <= 200.0 + 1e-9
    assert res.head_virtual.x_at(res.t_end) > 200.0
    assert math.isclose(res.head.x_at(res.t_end), 200.0, abs_tol=1e-6)


def test_zoom_fires_on_the_virtual_head_beyond_the_coiler():
    """The trigger lies past the coiler: without a virtual head it would never fire."""
    # the virtual head passes the coiler by at most the final strip length, so a
    # long slab is needed for the trigger to be reachable
    case = _case(
        _line([("R", 50.0)]),
        [_pass(1, "R", FWD, 100.0, 50.0, 4.0, zoom_pct=10.0, zoom_trigger=200.0)],
        slab_len=60.0,
    )
    res = simulate_piece(case, case.products[0])
    zoom = [e for e in res.events if e.kind == "zoom"]
    assert len(zoom) == 1
    assert zoom[0].x == pytest.approx(250.0)
    # the tail speeds up by 10%, until the coiler slowdown takes over
    slowdown = next(e for e in res.events if e.kind == "coiler_slowdown")
    assert res.tail.v_at(0.5 * (zoom[0].t + slowdown.t)) == pytest.approx(4.4, rel=1e-6)
    assert res.tail.v_at(res.t_end) == pytest.approx(1.0, abs=1e-6)


def test_section_event_deferred_to_disengagement():
    line = Line(
        (
            Equipment("ST", "start", 0.0, accel=1.0),
            Equipment("R", "stand", 50.0, accel=1.0),
            Equipment("DC", "coiler", 300.0, accel=1.0),
        ),
        (
            Section(
                "S1",
                x_start=0.0,
                length=300.0,
                events=(
                    SpeedEvent("S1-1", "S1", x_trigger=0.0, v_target=2.0),
                    # fires while the stand is rolling: must be deferred to tail-out
                    SpeedEvent("S1-2", "S1", x_trigger=60.0, v_target=6.0),
                ),
            ),
        ),
    )
    case = _case(line, [_pass(1, "R", FWD, 100.0, 50.0, 4.0)])
    res = simulate_piece(case, case.products[0])

    tail_out = next(e for e in res.events if e.kind == "tail_out")
    change = next(e for e in res.events if e.kind == "speed_change" and e.t > 0)
    assert change.t == pytest.approx(tail_out.t)
    assert "deferred" in change.detail
    # before disengagement the mill commands, not the roller table
    assert res.head.v_at(tail_out.t - 0.5) == pytest.approx(4.0)


def test_master_enforces_the_mass_balance_in_the_tandem():
    equipment = (
        Equipment("ST", "start", 0.0, accel=1.0),
        Equipment("F1", "stand", 50.0, accel=1.0, group="FM"),
        Equipment("F2", "stand", 60.0, accel=1.0, group="FM"),
        Equipment("DC", "coiler", 300.0, accel=1.0),
    )
    line = Line(
        equipment,
        (
            Section(
                "S1",
                x_start=0.0,
                length=300.0,
                events=(SpeedEvent("S1-1", "S1", x_trigger=0.0, v_target=2.0),),
            ),
        ),
    )
    case = _case(
        line,
        [
            _pass(1, "F1", FWD, 100.0, 50.0, 3.0),  # inconsistent on purpose
            _pass(2, "F2", FWD, 50.0, 25.0, 8.0, master=True),
        ],
    )
    harmonised, deviations = harmonise_tandem_speeds(case)
    speeds = {p.equipment_id: p.v_exit for p in harmonised.products[0].passes}
    assert speeds["F2"] == pytest.approx(8.0)
    assert speeds["F1"] == pytest.approx(4.0)
    assert len(deviations) == 1
    assert deviations[0].equipment_id == "F1"
    assert deviations[0].deviation_pct == pytest.approx(-33.333, abs=1e-3)


def test_an_unreachable_pass_gives_a_readable_error():
    line = _line([("R", 50.0)])
    case = _case(line, [_pass(1, "R", FWD, 100.0, 50.0, 4.0), _pass(2, "R", FWD, 50.0, 25.0, 8.0)])
    case = Case(
        line=case.line,
        products=case.products,
        settings=SimSettings(max_time=200.0),
    )
    with pytest.raises(ModelError, match="not reachable"):
        simulate_piece(case, case.products[0])


def test_validation_catches_the_broken_thickness_chain():
    line = _line([("R", 50.0)])
    case = _case(line, [_pass(1, "R", FWD, 90.0, 50.0, 4.0)])
    problems = [p.message for p in validate_case(case)]
    assert any("does not match" in p for p in problems)


def test_a_reverse_first_pass_is_rejected():
    line = _line([("R", 50.0)])
    case = _case(line, [_pass(1, "R", REV, 100.0, 50.0, 4.0)])
    problems = [p.message for p in validate_case(case)]
    assert any("first pass" in p for p in problems)


def test_coiler_waypoint_walks_backward_through_the_remaining_stands():
    """The tail speeds up at each tail-out, so the last-possible start is earlier."""
    f1 = _pass(1, "F1", FWD, 100.0, 50.0, 4.0)
    f2 = _pass(2, "F2", FWD, 50.0, 25.0, 8.0)
    engaged = [(f1, 50.0, 0.0), (f2, 60.0, 0.0)]

    x_wp, v_wp = coiler_tail_waypoint(30.0, 80.0, 1.0, 1.0, engaged)
    assert x_wp == pytest.approx(50.0)
    assert v_wp == pytest.approx(2.75)

    x_wp, v_wp = coiler_tail_waypoint(50.0, 80.0, 1.0, 1.0, [(f2, 60.0, 0.0)])
    assert x_wp == pytest.approx(60.0)
    assert v_wp == pytest.approx(41.0 ** 0.5 / 2.0)

    x_wp, v_wp = coiler_tail_waypoint(60.0, 80.0, 1.0, 1.0, [])
    assert x_wp == pytest.approx(80.0)
    assert v_wp == pytest.approx(1.0)

    # latest start after F1 tail-out: 4 m/s at 57.125 m lands on 1 m/s at the mandrel
    assert tail_arrival_speed(57.125, 4.0, 80.0, 1.0, [(f2, 60.0, 0.0)]) == pytest.approx(
        1.0, abs=1e-6
    )
    # waiting until the piece is free is too late: 8 m/s over 20 m at 1 m/s2
    assert tail_arrival_speed(60.0, 8.0, 80.0, 1.0, []) == pytest.approx(24.0 ** 0.5)


def test_the_finishing_mill_slows_down_while_the_tail_is_still_engaged():
    """Short run-out: braking after the last tail-out cannot reach 1 m/s."""
    line = _line([("F1", 50.0), ("F2", 60.0)], coiler_x=80.0)
    case = _case(
        line,
        [
            _pass(1, "F1", FWD, 100.0, 50.0, 4.0),
            _pass(2, "F2", FWD, 50.0, 25.0, 8.0),
        ],
    )
    res = simulate_piece(case, case.products[0])

    slowdown = next(e for e in res.events if e.kind == "coiler_slowdown")
    last_tail_out = max(e.t for e in res.events if e.kind == "tail_out")
    assert slowdown.t < last_tail_out
    assert "mill still rolling" in slowdown.detail
    assert res.tail.v_at(res.t_end) == pytest.approx(1.0, abs=1e-6)
    assert res.warnings == ()

    # while F2 is still engaged the tail decelerates at the coiler rate and the
    # lead at that rate times the remaining lambda
    t_mid = 0.5 * (slowdown.t + last_tail_out)
    assert res.tail.a_at(t_mid) == pytest.approx(-1.0, abs=1e-6)
    assert res.head_virtual.a_at(t_mid) == pytest.approx(-2.0, abs=1e-6)
    assert res.head_virtual.v_at(t_mid) / res.tail.v_at(t_mid) == pytest.approx(2.0, rel=1e-6)

    # after the last tail-out the body is rigid: both decelerate at the coiler rate
    t_free = last_tail_out + 0.05
    if t_free < res.t_end:
        assert res.head_virtual.v_at(t_free) == pytest.approx(res.tail.v_at(t_free), abs=1e-6)
        assert res.head_virtual.a_at(t_free) == pytest.approx(-1.0, abs=1e-6)


def test_an_impossible_coiler_slowdown_is_reported_even_with_the_mill():
    """At 0.05 m/s2 the latest start is already behind the tail at the last bite."""
    line = _line([("F1", 50.0), ("F2", 60.0)], coiler_x=68.0)
    equipment = tuple(
        replace(eq, accel=0.05) if eq.id == "DC" else eq for eq in line.equipment
    )
    line = Line(equipment, line.sections)
    case = _case(
        line,
        [
            _pass(1, "F1", FWD, 100.0, 50.0, 4.0),
            _pass(2, "F2", FWD, 50.0, 25.0, 8.0),
        ],
    )
    res = simulate_piece(case, case.products[0])
    assert any("cannot slow down" in w and "mill is still rolling" in w for w in res.warnings)
    assert res.tail.v_at(res.t_end) > 1.0


def test_a_reverse_last_pass_is_rejected():
    """Closing backwards, the piece would never reach the coiler."""
    line = _line([("R", 50.0)])
    case = _case(
        line,
        [
            _pass(1, "R", FWD, 100.0, 80.0, 3.0),
            _pass(2, "R", REV, 80.0, 60.0, 3.0, reversing_delay=4.0),
        ],
    )
    problems = [p.message for p in validate_case(case)]
    assert any("last pass" in p for p in problems)




def _two_coilers(
    stands: list[tuple[str, float]],
    dc1: float = 200.0,
    dc2: float = 230.0,
    v_start: float = 2.0,
    extra: list[Equipment] | None = None,
) -> Line:
    equipment = [Equipment("ST", "start", 0.0, accel=1.0)]
    equipment += [Equipment(name, "stand", x, accel=1.0) for name, x in stands]
    equipment.append(Equipment("DC1", "coiler", dc1, accel=1.0))
    equipment.append(Equipment("DC2", "coiler", dc2, accel=1.0))
    if extra:
        equipment.extend(extra)
    x_end = max(e.x for e in equipment if e.kind == "coiler")
    section = Section(
        "S1",
        x_start=0.0,
        length=x_end,
        events=(SpeedEvent("S1-1", "S1", x_trigger=0.0, v_target=v_start, direction=FWD),),
    )
    return Line(tuple(equipment), (section,))


def test_alternate_coilers_pin_at_their_own_position():
    case = replace(
        _case(_two_coilers([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)]),
        settings=SimSettings(n_pieces=4, coiler_pattern=("DC1", "DC2")),
    )
    results = simulate_case(case)
    assert [r.coiler_id for r in results] == ["DC1", "DC2", "DC1", "DC2"]
    assert results[0].x_coiler == pytest.approx(200.0)
    assert results[1].x_coiler == pytest.approx(230.0)
    assert max(s.x1 for s in results[0].head.segments) <= 200.0 + 1e-6
    assert max(s.x1 for s in results[1].head.segments) > 200.0 + 1e-3
    assert max(s.x1 for s in results[1].head.segments) <= 230.0 + 1e-6




def test_a_long_coiler_pattern_is_cycled():
    extra = [Equipment("DC3", "coiler", 260.0, accel=1.0)]
    case = replace(
        _case(
            _two_coilers([("R", 50.0)], extra=extra),
            [_pass(1, "R", FWD, 100.0, 50.0, 4.0)],
        ),
        settings=SimSettings(n_pieces=8, coiler_pattern=("DC1", "DC2", "DC1", "DC3")),
    )
    assert case.piece_coiler_ids == ("DC1", "DC2", "DC1", "DC3") * 2
    results = simulate_case(case)
    assert [r.coiler_id for r in results] == list(case.piece_coiler_ids)
    assert results[3].x_coiler == pytest.approx(260.0)


def test_two_coilers_without_a_pattern_are_rejected():
    case = _case(_two_coilers([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)])
    messages = [p.message for p in validate_case(case) if not p.is_warning]
    assert any("coiler_pattern is required" in m for m in messages)


def test_a_pattern_with_one_distinct_id_is_rejected():
    case = replace(
        _case(_two_coilers([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)]),
        settings=SimSettings(n_pieces=2, coiler_pattern=("DC1", "DC1")),
    )
    messages = [p.message for p in validate_case(case) if not p.is_warning]
    assert any("at least two distinct" in m for m in messages)


def test_an_unused_coiler_is_a_warning():
    extra = [Equipment("DC3", "coiler", 260.0, accel=1.0)]
    case = replace(
        _case(
            _two_coilers([("R", 50.0)], extra=extra),
            [_pass(1, "R", FWD, 100.0, 50.0, 4.0)],
        ),
        settings=SimSettings(n_pieces=2, coiler_pattern=("DC1", "DC2")),
    )
    warnings = [p.message for p in validate_case(case) if p.is_warning]
    assert any("DC3" in m and "not in coiler_pattern" in m for m in warnings)
    assert not [p for p in validate_case(case) if not p.is_warning]


def test_more_than_three_coilers_are_rejected():
    extra = [
        Equipment("DC3", "coiler", 260.0, accel=1.0),
        Equipment("DC4", "coiler", 280.0, accel=1.0),
    ]
    case = replace(
        _case(
            _two_coilers([("R", 50.0)], extra=extra),
            [_pass(1, "R", FWD, 100.0, 50.0, 4.0)],
        ),
        settings=SimSettings(n_pieces=2, coiler_pattern=("DC1", "DC2")),
    )
    messages = [p.message for p in validate_case(case) if not p.is_warning]
    assert any(f"at most {MAX_COILERS} coilers" in m for m in messages)


def test_the_cache_does_not_mix_coilers():
    case = replace(
        _case(_two_coilers([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)]),
        settings=SimSettings(n_pieces=4, coiler_pattern=("DC1", "DC2")),
    )
    base = base_results(case)
    assert ("P", "DC1") in base and ("P", "DC2") in base
    assert base[("P", "DC1")].x_coiler == pytest.approx(200.0)
    assert base[("P", "DC2")].x_coiler == pytest.approx(230.0)


def test_zoom_trigger_is_the_same_on_both_coilers():
    """TRoll ignores the downcoilers: virtual travel from the stand, not table plus wraps."""
    line = _two_coilers([("R", 50.0)], dc1=120.0, dc2=180.0)
    case = replace(
        _case(
            line,
            [_pass(1, "R", FWD, 100.0, 50.0, 4.0, zoom_pct=10.0, zoom_trigger=80.0)],
            slab_len=40.0,
        ),
        settings=SimSettings(n_pieces=2, coiler_pattern=("DC1", "DC2")),
    )
    dc1 = case.line.get("DC1")
    dc2 = case.line.get("DC2")
    near = simulate_piece(case, case.products[0], coiler=dc1)
    far = simulate_piece(case, case.products[0], coiler=dc2)
    zoom_near = next(e for e in near.events if e.kind == "zoom")
    zoom_far = next(e for e in far.events if e.kind == "zoom")
    assert zoom_near.x == pytest.approx(130.0)
    assert zoom_far.x == pytest.approx(zoom_near.x)
    assert near.x_coiler == pytest.approx(120.0)
    assert far.x_coiler == pytest.approx(180.0)
    assert far.head.x_at(far.t_end) > near.x_coiler + 1e-3


def test_negative_zoom_slows_the_tandem_down():
    case = _case(
        _line([("R", 50.0)]),
        [_pass(1, "R", FWD, 100.0, 50.0, 4.0, zoom_pct=-20.0, zoom_trigger=200.0)],
        slab_len=60.0,
    )
    res = simulate_piece(case, case.products[0])
    zoom = next(e for e in res.events if e.kind == "zoom")
    slowdown = next(e for e in res.events if e.kind == "coiler_slowdown")
    assert res.tail.v_at(0.5 * (zoom.t + slowdown.t)) == pytest.approx(3.2, rel=1e-6)


def test_zoom_pct_of_minus_100_is_rejected():
    case = _case(
        _line([("R", 50.0)]),
        [_pass(1, "R", FWD, 100.0, 50.0, 4.0, zoom_pct=-100.0, zoom_trigger=10.0)],
    )
    messages = [p.message for p in validate_case(case) if not p.is_warning]
    assert any("zoom_pct" in m and "-100" in m for m in messages)


def test_descaler_occupancy_uses_the_footprint():
    from hsmpace.example import example_case

    case, _ = harmonise_tandem_speeds(example_case())
    res = simulate_piece(case, case.products[0], coiler=case.line.get("DC1"))
    ds1 = [o for o in res.occupancy if o.equipment_id == "DS1"]
    ds2 = [o for o in res.occupancy if o.equipment_id == "DS2"]
    assert ds1 and ds2
    assert all(o.duration > 0.05 for o in ds1 + ds2)
    e1 = [o for o in res.occupancy if o.equipment_id == "E1"]
    assert e1 == []


def test_a_reversing_bar_can_occupy_a_marker_twice():
    equipment = (
        Equipment("ST", "start", 0.0, accel=1.0),
        Equipment("DS", "marker", 30.0, occupy=True, occupy_before=1.0, occupy_after=1.0),
        Equipment("R", "stand", 50.0, accel=1.0),
        Equipment("DC", "coiler", 400.0, accel=1.0),
    )
    line = Line(
        equipment,
        (
            Section(
                "S1",
                x_start=0.0,
                length=400.0,
                events=(SpeedEvent("S1-1", "S1", x_trigger=0.0, v_target=2.0),),
            ),
        ),
    )
    case = _case(
        line,
        [
            _pass(1, "R", FWD, 100.0, 80.0, 3.0, reversing_delay=1.0, reversing_clearance=25.0),
            _pass(2, "R", REV, 80.0, 60.0, 3.0, reversing_delay=1.0, reversing_clearance=6.0),
            _pass(3, "R", FWD, 60.0, 40.0, 3.0),
        ],
        slab_len=10.0,
    )
    res = simulate_piece(case, case.products[0])
    visits = [o for o in res.occupancy if o.equipment_id == "DS"]
    assert len(visits) >= 2


def _coilbox_line(x_cb: float = 100.0, x_r: float = 40.0, x_f: float = 160.0, x_dc: float = 240.0) -> Line:
    return Line(
        (
            Equipment("ST", "start", 0.0, accel=1.0),
            Equipment("R", "stand", x_r, accel=1.0),
            Equipment("CB", "coilbox", x_cb, accel=1.0),
            Equipment("F", "stand", x_f, accel=1.0),
            Equipment("DC", "coiler", x_dc, accel=1.0),
        ),
        (
            Section(
                "S1",
                x_start=0.0,
                length=x_r,
                events=(SpeedEvent("S1-1", "S1", x_trigger=0.0, v_target=2.0),),
            ),
            Section(
                "S2",
                x_start=x_r,
                length=x_cb - x_r,
                events=(SpeedEvent("S2-1", "S2", x_trigger=(x_r + x_cb) / 2, v_target=3.0),),
            ),
            Section(
                "S3",
                x_start=x_cb,
                length=x_f - x_cb,
                events=(SpeedEvent("S3-1", "S3", x_trigger=x_cb + 5.0, v_target=2.5),),
            ),
            Section("S4", x_start=x_f, length=x_dc - x_f),
        ),
    )


def _coilbox_case(
    *,
    x_cb: float = 100.0,
    thread_length: float = 0.0,
    delay: float = 0.0,
    v_thread: float = 2.0,
    v_coil: float = 3.0,
    v_uncoil: float = 2.0,
    slab_len: float = 10.0,
    n_pieces: int = 2,
    pacing: float = 80.0,
    x_f: float = 160.0,
    x_dc: float = 240.0,
) -> Case:
    product = Product(
        id="P",
        slab_thk=100.0,
        slab_wid=1000.0,
        slab_len=slab_len,
        passes=(
            _pass(1, "R", FWD, 100.0, 50.0, 4.0),
            _pass(2, "F", FWD, 50.0, 25.0, 8.0),
        ),
        coilbox_v_thread=v_thread,
        coilbox_v_coil=v_coil,
        coilbox_v_uncoil=v_uncoil,
        coilbox_thread_length=thread_length,
        coilbox_delay=delay,
    )
    return Case(
        line=_coilbox_line(x_cb=x_cb, x_f=x_f, x_dc=x_dc),
        products=(product,),
        settings=SimSettings(n_pieces=n_pieces, pacing=pacing),
    )


def test_coilbox_inverts_and_pays_out():
    from hsmpace.core.analysis import check_extremities

    case = _coilbox_case(delay=0.0, thread_length=0.0)
    res = simulate_piece(case, case.products[0])
    kinds = [e.kind for e in res.events]
    assert "coilbox_in" in kinds
    assert "coilbox_full" in kinds
    assert "coilbox_uncoil" in kinds
    assert "coilbox_empty" in kinds
    assert kinds.count("bite") == 2
    assert check_extremities(res) == []
    arrived = next(e for e in res.events if e.kind == "coilbox_in")
    empty = next(e for e in res.events if e.kind == "coilbox_empty")
    mid = 0.5 * (arrived.t + next(e.t for e in res.events if e.kind == "coilbox_full"))
    assert res.head.x_at(mid) == pytest.approx(100.0, abs=1e-6)
    assert res.tail.x_at(mid) < 100.0 - 0.5
    after = empty.t + 0.2
    assert res.head.x_at(after) > res.tail.x_at(after) + 0.1
    assert abs(res.length_error) < 0.5
    assert not any("overlap" in w for w in res.warnings)


def test_coilbox_thread_length_switches_to_coiling_speed():
    case = _coilbox_case(thread_length=12.0, v_thread=2.0, v_coil=3.5)
    res = simulate_piece(case, case.products[0])
    speeds = [e for e in res.events if e.kind == "coilbox_speed"]
    assert any("threading" in e.detail for e in speeds)
    assert any("coiling" in e.detail for e in speeds)


def test_coilbox_delay_holds_before_uncoiling():
    case = _coilbox_case(delay=2.5)
    res = simulate_piece(case, case.products[0])
    full = next(e for e in res.events if e.kind == "coilbox_full")
    uncoil = next(e for e in res.events if e.kind == "coilbox_uncoil")
    assert uncoil.t - full.t == pytest.approx(2.5, abs=1e-6)
    assert res.head.v_at(0.5 * (full.t + uncoil.t)) == pytest.approx(0.0, abs=1e-9)


def test_coilbox_warns_when_the_rougher_still_holds_the_tail():
    case = _coilbox_case(x_cb=48.0)
    res = simulate_piece(case, case.products[0])
    assert any("mill remains master" in w for w in res.warnings)


def test_two_coilboxes_are_rejected():
    line = _coilbox_line()
    extra = Equipment("CB2", "coilbox", 110.0, accel=1.0)
    case = replace(
        _coilbox_case(),
        line=Line(line.equipment + (extra,), line.sections),
    )
    messages = [p.message for p in validate_case(case) if not p.is_warning]
    assert any("at most one coilbox" in m for m in messages)


def test_product_can_bypass_the_coilbox():
    from hsmpace.core.analysis import check_extremities

    case = _coilbox_case()
    product = replace(case.products[0], use_coilbox=False)
    case = replace(case, products=(product,))
    res = simulate_piece(case, product)
    kinds = [e.kind for e in res.events]
    assert "coilbox_in" not in kinds
    assert "coilbox_full" not in kinds
    assert "coilbox_uncoil" not in kinds
    assert kinds.count("bite") == 2
    assert check_extremities(res) == []
    # the head crosses the axis without sitting there
    t_cross = res.head.crossing_times(100.0, direction=1)
    assert t_cross
    t = t_cross[0] + 1.0
    assert res.head.x_at(t) > 100.0 + 0.5
    assert res.tail.x_at(t) < res.head.x_at(t)


def test_bypass_ignores_coilbox_speeds_with_a_warning():
    case = _coilbox_case()
    product = replace(case.products[0], use_coilbox=False)
    case = replace(case, products=(product,))
    warnings = [p.message for p in validate_case(case) if p.is_warning]
    assert any("bypass" in m for m in warnings)


def test_empty_coilbox_tick_still_uses_the_box():
    case = _coilbox_case()
    assert case.products[0].use_coilbox is None
    assert case.products[0].uses_coilbox(case.line)
    res = simulate_piece(case, case.products[0])
    assert any(e.kind == "coilbox_in" for e in res.events)
    assert res.occupancy
    assert all(o.piece_id == res.piece_id for o in res.occupancy)


def test_unassigned_coiler_occupancy_is_not_working():
    from hsmpace.example import example_case

    case, _ = harmonise_tandem_speeds(example_case())
    res = simulate_piece(case, case.products[0], coiler=case.line.get("DC2"))
    by_id = {}
    for o in res.occupancy:
        if o.equipment_id in {"DC1", "DC2", "DC3"}:
            by_id.setdefault(o.equipment_id, []).append(o)
    assert by_id["DC2"] and all(o.working for o in by_id["DC2"])
    assert by_id["DC1"] and all(not o.working for o in by_id["DC1"])
    assert "DC3" not in by_id
    stands = [o for o in res.occupancy if o.equipment_id == "F7"]
    assert stands and all(o.working for o in stands)


def test_shifted_sequence_keeps_coiler_working_flags():
    from hsmpace.example import example_case

    case, _ = harmonise_tandem_speeds(example_case())
    sequenced = sequence(case, base_results(case), case.settings.pacing)
    second = sequenced[1]
    assert second.coiler_id == "DC2"
    dc1 = [o for o in second.occupancy if o.equipment_id == "DC1"]
    dc2 = [o for o in second.occupancy if o.equipment_id == "DC2"]
    assert dc2 and all(o.working for o in dc2)
    assert dc1 and all(not o.working for o in dc1)


def test_mass_balance_holds_when_f1_bites_during_coilbox_payout():
    """Transfer bar ~20 m, F1 15 m past the box: finishing bites with metal still stored."""
    case = _coilbox_case(x_cb=80.0, x_f=95.0, x_dc=180.0, delay=0.0)
    res = simulate_piece(case, case.products[0])
    f1 = next(e for e in res.events if e.kind == "bite" and e.equipment_id == "F")
    empty = next(e for e in res.events if e.kind == "coilbox_empty")
    assert f1.t < empty.t
    assert abs(res.length_error) < 0.1
    assert not any("mass balance" in w for w in res.warnings)


def test_follower_gap_sees_the_busy_coilbox_axis():
    from hsmpace.core.analysis import analyse_pair
    from hsmpace.core.simulate import shift_result

    case = _coilbox_case(pacing=30.0)
    first = simulate_piece(case, case.products[0])
    second = shift_result(first, 25.0, "#2")
    analysis = analyse_pair(first, second, gap_min=5.0, line=case.line)
    full = next(e for e in first.events if e.kind == "coilbox_full")
    empty = next(e for e in first.events if e.kind == "coilbox_empty")
    t = 0.5 * (full.t + empty.t)
    if second.t_start < t < second.t_end:
        expected = 100.0 - second.head.x_at(t)
        assert analysis.series.value_at(t) == pytest.approx(expected, abs=0.05)


def test_walking_beam_puts_the_slab_midpoint_on_the_start_row():
    case = _case(_line([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)], slab_len=10.0)
    case = replace(case, settings=replace(case.settings, tunnel_furnace=False))
    res = simulate_piece(case, case.products[0])
    assert res.head.x_at(0.0) == pytest.approx(5.0)
    assert res.tail.x_at(0.0) == pytest.approx(-5.0)

"""Speed at the bite: approach speed, the bite check, and speed changes near a stand."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from hsmpace.core.contract import case_from_dict
from hsmpace.core.model import (
    FWD,
    REV,
    Case,
    Equipment,
    Line,
    Product,
    RollingPass,
    Section,
    SimSettings,
    SpeedEvent,
    harmonise_tandem_speeds,
    validate_case,
)
from hsmpace.core.simulate import BITE_SPEED_TOLERANCE, PieceResult, simulate_piece
from hsmpace.core.studies import base_results
from hsmpace.example import example_case

NO_COILBOX_LINE = Path(__file__).parent / "data" / "no_coilbox_line.json"


def _line(
    stands: list[tuple[str, float]],
    coiler_x: float = 400.0,
    v_start: float = 2.0,
    extra_events: tuple[SpeedEvent, ...] = (),
    groups: dict[str, str] | None = None,
) -> Line:
    equipment = [Equipment("ST", "start", 0.0, accel=1.0)]
    equipment += [
        Equipment(name, "stand", x, accel=1.0, group=(groups or {}).get(name, ""))
        for name, x in stands
    ]
    equipment.append(Equipment("DC", "coiler", coiler_x, accel=1.0))
    section = Section(
        "S1",
        x_start=0.0,
        length=coiler_x,
        events=(SpeedEvent("S1-1", "S1", x_trigger=0.0, v_target=v_start),) + extra_events,
    )
    return Line(tuple(equipment), (section,))


def _case(line: Line, passes: list[RollingPass], slab_len: float = 10.0) -> Case:
    product = Product(
        id="P", slab_thk=100.0, slab_wid=1000.0, slab_len=slab_len, passes=tuple(passes)
    )
    return Case(line=line, products=(product,), settings=SimSettings(n_pieces=1))


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


def _run(case: Case) -> PieceResult:
    return simulate_piece(case, case.products[0])


def _bite(res: PieceResult, stand: str):
    return next(e for e in res.events if e.kind == "bite" and e.equipment_id == stand)


def _arrival(res: PieceResult, stand: str) -> float:
    return res.head_virtual.v_at(_bite(res, stand).t - 1e-6)


def _leaving(res: PieceResult, stand: str) -> float:
    return res.head_virtual.v_at(_bite(res, stand).t + 1e-6)


# R takes 100 -> 50 mm at 4 m/s, F takes 50 -> 25 mm at 2 m/s: the entry speed
# of F is 1 m/s, a quarter of the speed the bar leaves R with. The bar is 20 m
# long after R and the stands are 100 m apart, so it reaches F free of the mill.
def _rougher_then_finisher(extra_events=(), **f_kwargs) -> Case:
    return _case(
        _line([("R", 50.0), ("F", 150.0)], extra_events=extra_events),
        [
            _pass(1, "R", FWD, 100.0, 50.0, 4.0),
            _pass(2, "F", FWD, 50.0, 25.0, 2.0, **f_kwargs),
        ],
    )


# --- bite check ---------------------------------------------------------------


def test_a_bite_far_above_the_entry_speed_is_reported():
    res = _run(_rougher_then_finisher())

    assert _arrival(res, "F") == pytest.approx(4.0)
    assert _leaving(res, "F") == pytest.approx(8.0)
    assert len(res.warnings) == 1
    warning = res.warnings[0]
    assert "pass 2 on F" in warning
    assert "bites at 4.00 m/s" in warning
    assert "300% above the entry speed of the pass (1.00 m/s)" in warning
    assert "8.00 m/s instead of 2.00 m/s" in warning
    assert "approach_v_mps" in warning


@pytest.mark.parametrize(
    ("v_start", "warned"),
    [
        (2.0, False),
        (2.0 * (1.0 + BITE_SPEED_TOLERANCE) - 0.01, False),
        (2.0 * (1.0 + BITE_SPEED_TOLERANCE) + 0.01, True),
    ],
)
def test_the_bite_check_uses_a_ten_per_cent_tolerance(v_start, warned):
    assert BITE_SPEED_TOLERANCE == pytest.approx(0.10)
    case = _case(_line([("R", 50.0)], v_start=v_start), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)])
    res = _run(case)

    assert _arrival(res, "R") == pytest.approx(v_start)
    assert any("bites at" in w for w in res.warnings) is warned


def test_a_bite_below_the_entry_speed_is_ordinary_threading():
    # entry speed 4 m/s, the bar arrives at 2 m/s and the stand accelerates it
    case = _case(_line([("R", 50.0)]), [_pass(1, "R", FWD, 100.0, 50.0, 8.0)])
    res = _run(case)

    assert _arrival(res, "R") == pytest.approx(2.0)
    assert res.warnings == ()


def test_a_fast_bite_is_reported_once_for_the_whole_tandem():
    # the excess of the first bite runs through the second stand: one cause, one warning
    case = _case(
        _line([("R", 50.0), ("F1", 150.0), ("F2", 155.0)]),
        [
            _pass(1, "R", FWD, 100.0, 50.0, 4.0),
            _pass(2, "F1", FWD, 50.0, 25.0, 2.0),
            _pass(3, "F2", FWD, 25.0, 12.5, 4.0),
        ],
    )
    res = _run(case)

    assert _arrival(res, "F2") > 4.0
    fast = [w for w in res.warnings if "bites at" in w]
    assert len(fast) == 1
    assert "pass 2 on F1" in fast[0]


def test_inconsistent_tandem_speeds_are_reported_at_the_second_stand():
    # no group and no master: F2 is asked for the speed F1 already delivers
    case = _case(
        _line([("F1", 50.0), ("F2", 55.0)]),
        [
            _pass(1, "F1", FWD, 100.0, 50.0, 4.0),
            _pass(2, "F2", FWD, 50.0, 25.0, 4.0),
        ],
    )
    res = _run(case)

    fast = [w for w in res.warnings if "bites at" in w]
    assert len(fast) == 1
    assert "pass 2 on F2" in fast[0]
    assert "still in F1" in fast[0]
    assert "mass flow balance" in fast[0]


def test_the_built_in_example_bites_every_stand_within_tolerance():
    case, _ = harmonise_tandem_speeds(example_case())
    for result in base_results(case).values():
        assert result.warnings == ()


# --- approach speed -----------------------------------------------------------


def test_approach_speed_is_met_at_the_bite_of_a_pass_reached_from_another_stand():
    res = _run(_rougher_then_finisher(approach_v=1.0))

    assert _arrival(res, "F") == pytest.approx(1.0, abs=1e-4)
    assert _leaving(res, "F") == pytest.approx(2.0, abs=1e-4)
    assert res.warnings == ()
    # as late as possible: 4 -> 1 m/s at 1 m/s2 takes 7.5 m, so the bar still
    # runs at the roughing exit speed 8 m before the stand
    t_before = res.head_virtual.crossing_times(142.0, direction=FWD)[0]
    assert res.head_virtual.v_at(t_before) == pytest.approx(4.0)
    reached = [e for e in res.events if e.kind == "speed_change" and e.equipment_id == "F"]
    assert len(reached) == 1
    assert reached[0].t == pytest.approx(_bite(res, "F").t)
    assert "approach speed" in reached[0].detail


def test_without_an_approach_speed_the_bar_keeps_the_previous_exit_speed():
    res = _run(_rougher_then_finisher())

    t_before = res.head_virtual.crossing_times(149.0, direction=FWD)[0]
    assert res.head_virtual.v_at(t_before) == pytest.approx(4.0)


def test_approach_speed_can_also_speed_the_bar_up():
    res = _run(_rougher_then_finisher(approach_v=5.0))

    assert _arrival(res, "F") == pytest.approx(5.0, abs=1e-4)
    # 5 m/s is five times the entry speed: the request is met, and reported
    assert any("pass 2 on F" in w and "bites at 5.00 m/s" in w for w in res.warnings)


def test_approach_speed_starts_from_a_section_speed_change_on_the_way():
    # the transfer table first speeds the bar up, then the approach ramp is
    # planned from that speed and still ends on the stand
    event = SpeedEvent("S1-2", "S1", x_trigger=100.0, v_target=6.0)
    res = _run(_rougher_then_finisher(extra_events=(event,), approach_v=1.0))

    t_at_event = res.head_virtual.crossing_times(100.0, direction=FWD)[0]
    assert res.head_virtual.v_at(t_at_event) == pytest.approx(6.0, abs=1e-4)
    assert _arrival(res, "F") == pytest.approx(1.0, abs=1e-4)
    assert res.warnings == ()


def test_an_approach_ramp_without_room_reports_the_speed_reached():
    # 0.8 m of bar and 1 m between the stands: the ramp cannot fit
    case = _case(
        _line([("R", 50.0), ("F", 51.0)]),
        [
            _pass(1, "R", FWD, 100.0, 50.0, 4.0),
            _pass(2, "F", FWD, 50.0, 25.0, 2.0, approach_v=0.5),
        ],
        slab_len=0.4,
    )
    res = _run(case)

    assert _arrival(res, "F") > 3.0
    short = [w for w in res.warnings if "approach speed" in w and "Not enough distance" in w]
    assert len(short) == 1
    assert "pass 2 on F" in short[0] and "0.50 m/s requested" in short[0]


def test_approach_speed_is_not_applied_while_the_previous_stand_still_rolls():
    # 20 m of bar and 10 m between the stands: the mill commands, not the table
    case = _case(
        _line([("R", 50.0), ("F", 60.0)]),
        [
            _pass(1, "R", FWD, 100.0, 50.0, 4.0),
            _pass(2, "F", FWD, 50.0, 25.0, 2.0, approach_v=1.0),
        ],
    )
    res = _run(case)

    assert _arrival(res, "F") == pytest.approx(4.0)
    held = [w for w in res.warnings if "approach speed" in w]
    assert len(held) == 1
    assert "not applied" in held[0] and "still being rolled on R" in held[0]


def test_approach_speed_inside_a_tandem_group_is_a_validation_warning():
    case = _case(
        _line([("F1", 50.0), ("F2", 55.0)], groups={"F1": "FM", "F2": "FM"}),
        [
            _pass(1, "F1", FWD, 100.0, 50.0, 4.0),
            _pass(2, "F2", FWD, 50.0, 25.0, 8.0, approach_v=4.0),
        ],
    )
    problems = validate_case(case)

    assert all(p.is_warning for p in problems)
    assert any(
        p.locator == "pass:P:2" and "approach_v_mps is ignored inside the tandem" in p.message
        for p in problems
    )


def test_approach_speed_after_a_reversal_is_still_the_speed_the_piece_is_sent_at():
    case = _case(
        _line([("R", 50.0)]),
        [
            _pass(1, "R", FWD, 100.0, 80.0, 2.0, reversing_delay=3.0, reversing_clearance=4.0),
            _pass(
                2, "R", REV, 80.0, 60.0, 3.0,
                reversing_delay=3.0, reversing_clearance=4.0, approach_v=1.0,
            ),
            _pass(3, "R", FWD, 60.0, 50.0, 3.0),
        ],
    )
    res = _run(case)

    second = [e for e in res.events if e.kind == "bite"][1]
    # on a reverse pass the tail leads
    assert abs(res.tail.v_at(second.t - 1e-6)) == pytest.approx(1.0, abs=1e-4)
    assert not any(e.kind == "speed_change" and "approach" in e.detail for e in res.events)


# --- speed changes on and after a stand ---------------------------------------


@pytest.mark.parametrize("x_trigger", [150.0, 150.0 + 3e-14, 150.0 - 3e-14, 150.0 + 5e-7])
def test_a_speed_change_that_ends_on_the_stand_is_the_speed_at_the_bite(x_trigger):
    event = SpeedEvent("S1-2", "S1", x_trigger=x_trigger, v_target=1.0)
    res = _run(_rougher_then_finisher(extra_events=(event,)))

    assert _arrival(res, "F") == pytest.approx(1.0, abs=1e-4)
    assert _leaving(res, "F") == pytest.approx(2.0, abs=1e-4)
    assert res.warnings == ()
    changes = [e for e in res.events if e.kind == "speed_change" and e.t > 0]
    # met once, at the bite, and not applied again when the mill releases the strip
    assert len(changes) == 1
    assert changes[0].t == pytest.approx(_bite(res, "F").t)
    assert "reached here as requested" in changes[0].detail


def test_approach_speed_wins_over_a_speed_change_on_the_same_stand():
    event = SpeedEvent("S1-2", "S1", x_trigger=150.0, v_target=3.0)
    res = _run(_rougher_then_finisher(extra_events=(event,), approach_v=1.0))

    assert _arrival(res, "F") == pytest.approx(1.0, abs=1e-4)
    assert len(res.warnings) == 1
    assert "section event S1-2: 3.00 m/s requested" in res.warnings[0]
    assert "approach_v_mps of pass 2 takes precedence" in res.warnings[0]


def test_a_speed_change_after_the_stand_is_held_and_applied_at_disengagement():
    event = SpeedEvent("S1-2", "S1", x_trigger=60.0, v_target=6.0)
    case = _case(
        _line([("R", 50.0)], extra_events=(event,)), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)]
    )
    res = _run(case)

    tail_out = next(e for e in res.events if e.kind == "tail_out")
    change = next(e for e in res.events if e.kind == "speed_change" and e.t > 0)
    assert change.t == pytest.approx(tail_out.t)
    assert "deferred" in change.detail
    assert res.warnings == ()


def test_a_held_speed_change_cancelled_by_the_coiler_slowdown_is_reported():
    # the coiler is 5 m after the stand: the slowdown starts while the mill
    # still rolls, so the speed change held since x = 52 m is never applied
    event = SpeedEvent("S1-2", "S1", x_trigger=52.0, v_target=1.5)
    case = _case(
        _line([("R", 50.0)], coiler_x=55.0, extra_events=(event,)),
        [_pass(1, "R", FWD, 100.0, 50.0, 4.0)],
    )
    res = _run(case)

    slowdown = next(e for e in res.events if e.kind == "coiler_slowdown")
    assert "mill still rolling" in slowdown.detail
    assert not any(e.kind == "speed_change" and e.t > 0 for e in res.events)
    dropped = [w for w in res.warnings if "was not applied" in w]
    assert len(dropped) == 1
    assert "section event S1-2: 1.50 m/s at x=52.0 m" in dropped[0]
    assert "being rolled on R" in dropped[0]
    assert "slowdown towards the coiler" in dropped[0]


def test_a_held_speed_change_replaced_by_a_later_one_is_reported():
    events = (
        SpeedEvent("S1-2", "S1", x_trigger=55.0, v_target=5.0),
        SpeedEvent("S1-3", "S1", x_trigger=60.0, v_target=6.0),
    )
    case = _case(
        _line([("R", 50.0)], extra_events=events), [_pass(1, "R", FWD, 100.0, 50.0, 4.0)]
    )
    res = _run(case)

    applied = [e for e in res.events if e.kind == "speed_change" and e.t > 0]
    assert len(applied) == 1 and "6.00 m/s" in applied[0].detail
    replaced = [w for w in res.warnings if "was not applied" in w]
    assert len(replaced) == 1
    assert "section event S1-2" in replaced[0] and "section event S1-3 replaced it" in replaced[0]


# --- a line without a coilbox, as a TRoll import of it used to look -----------
#
# tests/data/no_coilbox_line.json holds invented numbers: a reversing rougher,
# six finishing stands, two coilers, and nothing that slows the transfer bar
# between the last roughing pass (4.5 m/s) and F1 (entry speed 0.6 m/s).


def _no_coilbox_line() -> Case:
    return case_from_dict(json.loads(NO_COILBOX_LINE.read_text(encoding="utf-8")))


def _with_f1_approach(case: Case) -> Case:
    """What the TRoll import now writes: F1 entry speed on the F1 row, per product."""
    products = tuple(
        replace(
            product,
            passes=tuple(
                replace(rp, approach_v=rp.v_entry) if rp.equipment_id == "F1" else rp
                for rp in product.passes
            ),
        )
        for product in case.products
    )
    return replace(case, products=products)


def _with_section_event(case: Case, x_trigger: float, v_target: float) -> Case:
    section = case.line.sections[0]
    event = SpeedEvent(f"{section.id}-2", section.id, x_trigger=x_trigger, v_target=v_target)
    return replace(
        case,
        line=Line(case.line.equipment, (replace(section, events=section.events + (event,)),)),
    )


def _piece(case: Case, product_id: str = "PA") -> PieceResult:
    return simulate_piece(
        case, case.product(product_id), piece_id=product_id, coiler=case.line.get("DC1")
    )


def _finishing_exit_speeds(res: PieceResult) -> list[float]:
    return [_leaving(res, f"F{k}") for k in range(1, 7)]


def _tail_time_on_the_runout(res: PieceResult) -> float:
    last_tail_out = max(e.t for e in res.events if e.kind == "tail_out")
    return res.tail.t_end - last_tail_out


def test_without_a_slowdown_the_bar_hits_f1_at_roughing_speed_and_it_is_reported():
    res = _piece(_no_coilbox_line())

    assert _arrival(res, "F1") == pytest.approx(4.5, abs=1e-3)
    # 5 m/s scheduled at the last stand
    assert _finishing_exit_speeds(res)[-1] == pytest.approx(23.96, abs=0.01)
    # the tail crawls along the 112 m run-out table at the final coiler speed
    assert _tail_time_on_the_runout(res) == pytest.approx(111.6, abs=0.1)
    assert len(res.warnings) == 1
    assert "pass 6 on F1: the piece bites at 4.50 m/s" in res.warnings[0]
    assert "650% above the entry speed of the pass (0.60 m/s)" in res.warnings[0]


@pytest.mark.parametrize(("product_id", "v_entry"), [("PA", 0.6), ("PB", 0.45)])
def test_with_f1_approach_each_product_enters_at_its_own_schedule_speed(product_id, v_entry):
    case = _with_f1_approach(_no_coilbox_line())
    res = _piece(case, product_id)
    schedule = [rp.v_exit for rp in case.product(product_id).passes if rp.equipment_id != "RM"]

    assert _arrival(res, "F1") == pytest.approx(v_entry, abs=1e-3)
    assert _finishing_exit_speeds(res) == pytest.approx(schedule, abs=1e-3)
    assert res.warnings == ()
    # the run-out table in about 20 s instead of 112 s
    assert _tail_time_on_the_runout(res) < 25.0
    assert res.tail.v_at(res.tail.t_end - 1e-6) == pytest.approx(1.0, abs=1e-3)
    assert res.length_kinematic == pytest.approx(res.length_geometric, rel=1e-9)


def test_a_speed_change_typed_on_f1_is_met_at_the_bite():
    # a distance of 216.7 m from a section starting at -12.4 m is one rounding
    # away from the F1 coordinate: 204.29999999999998 against 204.3
    x_trigger = -12.4 + 216.7
    assert x_trigger != 204.3
    res = _piece(_with_section_event(_no_coilbox_line(), x_trigger, 0.6))

    assert _arrival(res, "F1") == pytest.approx(0.6, abs=1e-3)
    assert _finishing_exit_speeds(res)[-1] == pytest.approx(5.0, abs=1e-3)
    assert res.warnings == ()


def test_a_speed_change_typed_after_f1_is_reported_as_not_applied():
    res = _piece(_with_section_event(_no_coilbox_line(), 205.5, 0.6))

    assert _arrival(res, "F1") == pytest.approx(4.5, abs=1e-3)
    assert any("pass 6 on F1: the piece bites at 4.50 m/s" in w for w in res.warnings)
    dropped = [w for w in res.warnings if "was not applied" in w]
    assert len(dropped) == 1
    assert "section event S1-2: 0.60 m/s at x=205.5 m" in dropped[0]
    assert "being rolled on F1" in dropped[0]
    assert "end the change at or before it" in dropped[0]

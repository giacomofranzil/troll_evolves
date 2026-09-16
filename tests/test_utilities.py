"""Post-process water and power from occupancy. Not part of the event loop."""

from __future__ import annotations

from dataclasses import replace

import pytest

from hsmpace.core.analysis import analyse_sequence
from hsmpace.core.contract import report_to_dict
from hsmpace.core.kinematics import Segment, Trajectory
from hsmpace.core.model import (
    UTILITY_POWER,
    UTILITY_WATER,
    WHEN_OCCUPY,
    WHEN_ROLLING,
    UtilityRecipe,
    harmonise_tandem_speeds,
    validate_case,
)
from hsmpace.core.occupancy import Occupancy
from hsmpace.core.simulate import PieceResult
from hsmpace.core.studies import base_results, sequence
from hsmpace.core.utilities import analyse_utilities, quantity_of
from hsmpace.example import example_case


def _dummy_result(piece_id: str, occupancy: list[Occupancy]) -> PieceResult:
    dummy = Trajectory([Segment(0.0, 1.0, 0.0, 0.0, 0.0)])
    return PieceResult(
        piece_id=piece_id,
        product_id="P1",
        t_release=0.0,
        head=dummy,
        tail=dummy,
        head_virtual=dummy,
        occupancy=tuple(occupancy),
    )


def test_quantity_of_water_is_rate_times_seconds():
    assert quantity_of(UTILITY_WATER, 120.0, 10.0) == pytest.approx(1200.0)


def test_quantity_of_power_converts_kw_seconds_to_kwh():
    assert quantity_of(UTILITY_POWER, 3600.0, 1.0) == pytest.approx(1.0)
    assert quantity_of(UTILITY_POWER, 8000.0, 3600.0) == pytest.approx(8000.0)


def test_quantity_of_is_zero_for_empty_span_or_unknown_kind():
    assert quantity_of(UTILITY_WATER, 120.0, 0.0) == 0.0
    assert quantity_of("steam", 1.0, 10.0) == 0.0


def test_no_recipes_yields_an_empty_report():
    case, _ = harmonise_tandem_speeds(replace(example_case(), utilities=()))
    results = sequence(case, base_results(case), case.settings.pacing)
    usage = analyse_utilities(case, results)
    assert usage.empty
    assert usage.water_m3 == 0.0
    assert usage.power_kwh == 0.0
    assert usage.draws == ()


def test_ds1_water_follows_occupancy_duration():
    case, _ = harmonise_tandem_speeds(
        replace(
            example_case(),
            utilities=(UtilityRecipe("DS1", UTILITY_WATER, 120.0, WHEN_OCCUPY),),
        )
    )
    from hsmpace.core.simulate import simulate_piece

    res = simulate_piece(case, case.products[0], coiler=case.line.get("DC1"))
    ds1 = [o for o in res.occupancy if o.equipment_id == "DS1"]
    assert ds1
    usage = analyse_utilities(case, [res])
    litres = sum(120.0 * o.duration for o in ds1)
    assert usage.water_m3 == pytest.approx(litres / 1000.0)
    assert usage.power_kwh == 0.0
    assert all(d.equipment_id == "DS1" and d.utility == UTILITY_WATER for d in usage.draws)


def test_overlapping_pieces_add_instantaneous_rates():
    case = replace(
        example_case(),
        utilities=(UtilityRecipe("DS1", UTILITY_WATER, 120.0, WHEN_OCCUPY),),
    )
    first = _dummy_result(
        "#1", [Occupancy("DS1", 1, t_in=0.0, t_out=10.0, piece_id="#1")]
    )
    second = _dummy_result(
        "#2", [Occupancy("DS1", 1, t_in=5.0, t_out=15.0, piece_id="#2")]
    )
    usage = analyse_utilities(case, [first, second])

    assert usage.water_m3 == pytest.approx(2.4)
    by_t = {p.t: p.rate for p in usage.water_series}
    assert by_t[0.0] == pytest.approx(120.0)
    assert by_t[5.0] == pytest.approx(240.0)
    assert by_t[10.0] == pytest.approx(120.0)
    assert by_t[15.0] == pytest.approx(0.0)


def test_rolling_on_a_marker_is_rejected():
    case = replace(
        example_case(),
        utilities=(UtilityRecipe("DS1", UTILITY_WATER, 10.0, WHEN_ROLLING),),
    )
    messages = [p.message for p in validate_case(case) if not p.is_warning]
    assert any("rolling" in m and "DS1" in m for m in messages)


def test_rolling_recipe_is_ignored_on_marker_occupancy():
    """Validation rejects it; the post-process must still not consume."""
    case = replace(
        example_case(),
        utilities=(UtilityRecipe("DS1", UTILITY_WATER, 120.0, WHEN_ROLLING),),
    )
    piece = _dummy_result(
        "#1", [Occupancy("DS1", 1, t_in=0.0, t_out=10.0, piece_id="#1")]
    )
    usage = analyse_utilities(case, [piece])
    assert usage.empty


def test_occupy_off_warns_and_consumes_nothing():
    case, _ = harmonise_tandem_speeds(
        replace(
            example_case(),
            utilities=(UtilityRecipe("E1", UTILITY_WATER, 10.0, WHEN_OCCUPY),),
        )
    )
    warnings = [p.message for p in validate_case(case) if p.is_warning]
    assert any("occupy is off" in m for m in warnings)

    from hsmpace.core.simulate import simulate_piece

    res = simulate_piece(case, case.products[0], coiler=case.line.get("DC1"))
    assert all(o.equipment_id != "E1" for o in res.occupancy)
    usage = analyse_utilities(case, [res])
    assert usage.empty


def test_unknown_equipment_and_invalid_kind_are_rejected():
    bad_eq = replace(
        example_case(),
        utilities=(UtilityRecipe("NOPE", UTILITY_WATER, 1.0, WHEN_OCCUPY),),
    )
    bad_kind = replace(
        example_case(),
        utilities=(UtilityRecipe("DS1", "steam", 1.0, WHEN_OCCUPY),),
    )
    bad_rate = replace(
        example_case(),
        utilities=(UtilityRecipe("DS1", UTILITY_WATER, -1.0, WHEN_OCCUPY),),
    )
    assert any("unknown equipment" in p.message for p in validate_case(bad_eq))
    assert any("steam" in p.message for p in validate_case(bad_kind))
    assert any("negative" in p.message for p in validate_case(bad_rate))


def test_rolling_power_on_stands_integrates_to_kwh():
    case = replace(
        example_case(),
        utilities=(UtilityRecipe("R1", UTILITY_POWER, 7200.0, WHEN_ROLLING),),
    )
    piece = _dummy_result(
        "#1", [Occupancy("R1", 1, t_in=0.0, t_out=1800.0, piece_id="#1")]
    )
    usage = analyse_utilities(case, [piece])
    # 7200 kW for 1800 s = 3600 kWh
    assert usage.power_kwh == pytest.approx(3600.0)
    assert usage.water_m3 == 0.0
    assert usage.draws[0].when == WHEN_ROLLING


def test_json_report_carries_utility_totals():
    case, deviations = harmonise_tandem_speeds(example_case())
    results = sequence(case, base_results(case), case.settings.pacing)
    analyses = analyse_sequence(results, case.settings.gap_min, case.line)
    report = report_to_dict(case, results, analyses, deviations)

    assert report["utilities"]["water_m3"] > 0.0
    assert report["utilities"]["power_kwh"] > 0.0
    draws = report["utilities"]["draws"]
    assert any(d["equipment_id"] == "DS1" and d["utility"] == "water" for d in draws)
    assert any(d["equipment_id"] == "F1" and d["utility"] == "power" for d in draws)


def test_analyse_utilities_does_not_need_the_simulator():
    """Recipes attach to occupancy already computed; the event loop is untouched."""
    case = replace(
        example_case(),
        utilities=(UtilityRecipe("DS1", UTILITY_WATER, 50.0, WHEN_OCCUPY),),
    )
    piece = _dummy_result(
        "A", [Occupancy("DS1", 1, t_in=2.0, t_out=4.0, piece_id="A")]
    )
    usage = analyse_utilities(case, [piece])
    assert usage.draws[0].quantity == pytest.approx(100.0)
    assert usage.water_m3 == pytest.approx(0.1)

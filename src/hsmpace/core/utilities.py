"""Utility consumption from occupancy intervals.

Water and electrical power are not part of the event loop: after the run, each
recipe is applied to the busy spans of a device. Instantaneous rate is piecewise
constant; the integral is rate times duration. Overlapping pieces add.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import (
    KIND_STAND,
    UTILITY_POWER,
    UTILITY_WATER,
    WHEN_ROLLING,
    Case,
    UtilityRecipe,
)
from .occupancy import Occupancy
from .simulate import PieceResult


@dataclass(frozen=True)
class UtilityDraw:
    """One recipe applied to one occupancy span of one piece."""

    piece_id: str
    equipment_id: str
    utility: str
    when: str
    t_in: float
    t_out: float
    rate: float
    quantity: float
    """Litres for water, kWh for power."""

    @property
    def duration(self) -> float:
        return self.t_out - self.t_in


@dataclass(frozen=True)
class RatePoint:
    t: float
    rate: float


@dataclass(frozen=True)
class UtilityReport:
    draws: tuple[UtilityDraw, ...]
    water_series: tuple[RatePoint, ...]
    power_series: tuple[RatePoint, ...]
    water_m3: float
    power_kwh: float

    @property
    def empty(self) -> bool:
        return not self.draws


def quantity_of(utility: str, rate: float, duration: float) -> float:
    """Integrated consumption: litres (water) or kWh (power)."""
    if duration <= 0.0 or rate == 0.0:
        return 0.0
    if utility == UTILITY_WATER:
        return rate * duration
    if utility == UTILITY_POWER:
        return rate * duration / 3600.0
    return 0.0


def _matches(recipe: UtilityRecipe, occ: Occupancy, kind: str) -> bool:
    if occ.equipment_id != recipe.equipment_id:
        return False
    if occ.duration <= 1e-9:
        return False
    if recipe.when == WHEN_ROLLING:
        return kind == KIND_STAND
    return True


def _step_series(draws: tuple[UtilityDraw, ...], utility: str) -> tuple[RatePoint, ...]:
    relevant = [d for d in draws if d.utility == utility]
    if not relevant:
        return ()
    knots = sorted({d.t_in for d in relevant} | {d.t_out for d in relevant})
    points: list[RatePoint] = []
    for t in knots:
        rate = sum(d.rate for d in relevant if d.t_in <= t < d.t_out - 1e-12)
        points.append(RatePoint(t, rate))
    return tuple(points)


def analyse_utilities(case: Case, results: list[PieceResult]) -> UtilityReport:
    """Apply the case recipes to occupancy. Does not call the simulator."""
    draws: list[UtilityDraw] = []
    if not case.utilities:
        return UtilityReport((), (), (), 0.0, 0.0)

    kinds = {e.id: e.kind for e in case.line.equipment}
    for res in results:
        for occ in res.occupancy:
            kind = kinds.get(occ.equipment_id, "")
            for recipe in case.utilities:
                if not _matches(recipe, occ, kind):
                    continue
                duration = occ.duration
                draws.append(
                    UtilityDraw(
                        piece_id=res.piece_id,
                        equipment_id=occ.equipment_id,
                        utility=recipe.utility,
                        when=recipe.when,
                        t_in=occ.t_in,
                        t_out=occ.t_out,
                        rate=recipe.rate,
                        quantity=quantity_of(recipe.utility, recipe.rate, duration),
                    )
                )

    ordered = tuple(sorted(draws, key=lambda d: (d.t_in, d.equipment_id, d.piece_id)))
    water_l = sum(d.quantity for d in ordered if d.utility == UTILITY_WATER)
    power_kwh = sum(d.quantity for d in ordered if d.utility == UTILITY_POWER)
    return UtilityReport(
        draws=ordered,
        water_series=_step_series(ordered, UTILITY_WATER),
        power_series=_step_series(ordered, UTILITY_POWER),
        water_m3=water_l / 1000.0,
        power_kwh=power_kwh,
    )

"""Device occupancy: overlap of the piece envelope with a station footprint.

A device is busy when ``[tail, head]`` overlaps ``[x - occupy_before, x + occupy_after]``.
This module is post-process on the trajectories: it does not run inside the event loop.
Utility consumption (water, power) attaches to these intervals in ``utilities.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .kinematics import overlap_intervals
from .model import KIND_STAND, Line


@dataclass(frozen=True)
class Occupancy:
    equipment_id: str
    pass_no: int
    t_in: float
    t_out: float
    piece_id: str = ""

    @property
    def duration(self) -> float:
        return self.t_out - self.t_in


def stamp_piece(occupancy: tuple[Occupancy, ...], piece_id: str) -> tuple[Occupancy, ...]:
    """Attach the piece identifier after the geometric spans are known."""
    return tuple(
        Occupancy(o.equipment_id, o.pass_no, o.t_in, o.t_out, piece_id) for o in occupancy
    )


def finalise_occupancy(
    line: Line,
    head,
    tail,
    stand_occ: list[Occupancy],
) -> tuple[Occupancy, ...]:
    """Stand visits plus footprint overlap of every device marked occupy."""
    out: list[Occupancy] = []
    for o in stand_occ:
        eq = line.get(o.equipment_id)
        if not eq.occupies:
            continue
        spans = overlap_intervals(head, tail, eq.occupy_lo, eq.occupy_hi)
        chosen: tuple[float, float] | None = None
        for a, b in spans:
            if a <= o.t_in + 1e-4 and b >= o.t_out - 1e-4:
                chosen = (a, b)
                break
        if chosen is None:
            overlapping = [
                (a, b) for a, b in spans if a < o.t_out - 1e-9 and b > o.t_in + 1e-9
            ]
            if overlapping:
                chosen = overlapping[0]
        if chosen is not None:
            out.append(Occupancy(o.equipment_id, o.pass_no, chosen[0], chosen[1]))
        else:
            out.append(o)
    for eq in line.equipment:
        if not eq.occupies or eq.kind == KIND_STAND:
            continue
        spans = overlap_intervals(head, tail, eq.occupy_lo, eq.occupy_hi)
        for i, (a, b) in enumerate(spans, start=1):
            out.append(Occupancy(eq.id, i, a, b))
    return tuple(sorted(out, key=lambda item: (item.t_in, item.equipment_id, item.pass_no)))

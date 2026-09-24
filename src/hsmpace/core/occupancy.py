"""Device occupancy: overlap of the piece envelope with a station footprint.

A device is busy when ``[tail, head]`` overlaps ``[x - occupy_before, x + occupy_after]``.
This module is post-process on the trajectories: it does not run inside the event loop.
Utility consumption (water, power) attaches to these intervals in ``utilities.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .kinematics import overlap_intervals
from .model import KIND_COILER, KIND_STAND, Line


@dataclass(frozen=True)
class Occupancy:
    equipment_id: str
    pass_no: int
    t_in: float
    t_out: float
    piece_id: str = ""
    working: bool = True
    """True when the device is working on this piece. Coilers covered by the
    strip but not assigned to it stay occupied (pacing) with working=False."""

    @property
    def duration(self) -> float:
        return self.t_out - self.t_in


def stamp_piece(occupancy: tuple[Occupancy, ...], piece_id: str) -> tuple[Occupancy, ...]:
    """Attach the piece identifier after the geometric spans are known."""
    return tuple(replace(o, piece_id=piece_id) for o in occupancy)


def classify_working(
    occupancy: tuple[Occupancy, ...],
    line: Line,
    coiler_id: str,
) -> tuple[Occupancy, ...]:
    """Tag coiler spans that are passage, not coiling.

    Default is working. A coiler whose id is not the piece's assigned
    ``coiler_id`` stays geometrically busy (the strip is there) but does not
    work on that piece.
    """
    kinds = {e.id: e.kind for e in line.equipment}
    out: list[Occupancy] = []
    for o in occupancy:
        if kinds.get(o.equipment_id) == KIND_COILER and o.equipment_id != coiler_id:
            out.append(replace(o, working=False))
        else:
            out.append(replace(o, working=True))
    return tuple(out)


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

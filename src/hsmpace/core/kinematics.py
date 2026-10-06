"""Analytic segment kinematic engine.

Every stretch of motion is uniformly accelerated:

    x(t) = x0 + v0 * (t - t0) + 0.5 * a * (t - t0)**2

Trajectories are therefore exact and represented by a few dozen segments rather
than hundreds of thousands of samples. The difference between two trajectories
is a piecewise quadratic function, so the instants at which the gap between two
pieces touches a threshold are found by solving quadratic equations, with no
sampling and no integration error.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EPS_T = 1e-9
EPS_X = 1e-9


@dataclass(frozen=True)
class Segment:
    """Uniformly accelerated stretch of motion valid on [t0, t1]."""

    t0: float
    t1: float
    x0: float
    v0: float
    a: float = 0.0

    def x_at(self, t: float) -> float:
        dt = t - self.t0
        return self.x0 + self.v0 * dt + 0.5 * self.a * dt * dt

    def v_at(self, t: float) -> float:
        return self.v0 + self.a * (t - self.t0)

    @property
    def x1(self) -> float:
        return self.x_at(self.t1)

    @property
    def v1(self) -> float:
        return self.v_at(self.t1)

    @property
    def duration(self) -> float:
        return self.t1 - self.t0


def solve_crossing(
    seg_t0: float,
    x0: float,
    v0: float,
    a: float,
    target: float,
    t_from: float,
    t_to: float,
    direction: int = 0,
) -> float | None:
    """First instant in [t_from, t_to] at which x(t) reaches ``target``.

    ``direction`` filters the sense of the crossing: +1 accepts only crossings
    with positive velocity, -1 only with negative velocity, 0 accepts both.
    Returns ``None`` when the crossing does not happen inside the window.
    """
    # x(tau) - target = 0 with tau = t - seg_t0
    c = x0 - target
    b = v0
    a2 = 0.5 * a

    roots: list[float] = []
    if abs(a2) < 1e-15:
        if abs(b) > 1e-15:
            roots.append(-c / b)
        elif abs(c) < EPS_X:
            roots.append(0.0)
    else:
        disc = b * b - 4.0 * a2 * c
        if disc >= 0.0:
            sq = math.sqrt(disc)
            roots.append((-b - sq) / (2.0 * a2))
            roots.append((-b + sq) / (2.0 * a2))

    best: float | None = None
    for tau in sorted(roots):
        t = seg_t0 + tau
        if t < t_from - EPS_T or t > t_to + EPS_T:
            continue
        t = min(max(t, t_from), t_to)
        if direction != 0:
            v = v0 + a * (t - seg_t0)
            if direction > 0 and v < -EPS_X:
                continue
            if direction < 0 and v > EPS_X:
                continue
        if best is None or t < best:
            best = t
    return best


class Trajectory:
    """Contiguous sequence of segments.

    Position is continuous between consecutive segments; velocity may be
    discontinuous, which is physically correct at bites and tail-outs.
    """

    __slots__ = ("segments",)

    def __init__(self, segments: list[Segment] | None = None) -> None:
        self.segments: list[Segment] = list(segments or [])

    def __len__(self) -> int:
        return len(self.segments)

    def __bool__(self) -> bool:
        return bool(self.segments)

    def append(self, seg: Segment) -> None:
        if seg.t1 < seg.t0 - EPS_T:
            raise ValueError("segment with negative duration")
        if seg.duration <= EPS_T and self.segments:
            return
        self.segments.append(seg)

    @property
    def t_start(self) -> float:
        return self.segments[0].t0

    @property
    def t_end(self) -> float:
        return self.segments[-1].t1

    def _find(self, t: float) -> Segment:
        segs = self.segments
        if t <= segs[0].t0:
            return segs[0]
        if t >= segs[-1].t1:
            return segs[-1]
        lo, hi = 0, len(segs) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if t < segs[mid].t1:
                hi = mid
            else:
                lo = mid + 1
        return segs[lo]

    def x_at(self, t: float) -> float:
        seg = self._find(t)
        t = min(max(t, seg.t0), seg.t1)
        return seg.x_at(t)

    def v_at(self, t: float) -> float:
        seg = self._find(t)
        t = min(max(t, seg.t0), seg.t1)
        return seg.v_at(t)

    def a_at(self, t: float) -> float:
        return self._find(t).a

    def shift(self, dt: float) -> "Trajectory":
        return Trajectory(
            [Segment(s.t0 + dt, s.t1 + dt, s.x0, s.v0, s.a) for s in self.segments]
        )

    def clamp_max(self, x_max: float) -> "Trajectory":
        """Pin the trajectory at ``x_max`` (head gripped by the coiler)."""
        out: list[Segment] = []
        clamped = False
        for s in self.segments:
            if clamped:
                out.append(Segment(s.t0, s.t1, x_max, 0.0, 0.0))
                continue
            if s.x0 >= x_max - EPS_X:
                clamped = True
                out.append(Segment(s.t0, s.t1, x_max, 0.0, 0.0))
                continue
            t_hit = solve_crossing(s.t0, s.x0, s.v0, s.a, x_max, s.t0, s.t1, direction=1)
            if t_hit is None:
                out.append(s)
                continue
            if t_hit > s.t0 + EPS_T:
                out.append(Segment(s.t0, t_hit, s.x0, s.v0, s.a))
            if t_hit < s.t1 - EPS_T:
                out.append(Segment(t_hit, s.t1, x_max, 0.0, 0.0))
            clamped = True
        return Trajectory(out)

    def clamp_max_window(self, x_max: float, t_lo: float, t_hi: float) -> "Trajectory":
        """``min(x, x_max)`` only on ``[t_lo, t_hi]``; the rest is unchanged.

        Used for the coilbox gap: while the box is busy the follower sees the
        closer of the leader's tail and the box axis.
        """
        if t_hi <= t_lo + EPS_T:
            return Trajectory(list(self.segments))
        out: list[Segment] = []
        for s in self.segments:
            cuts = [s.t0]
            if s.t0 < t_lo < s.t1:
                cuts.append(t_lo)
            if s.t0 < t_hi < s.t1:
                cuts.append(t_hi)
            cuts.append(s.t1)
            for a, b in zip(cuts[:-1], cuts[1:]):
                if b <= a + EPS_T:
                    continue
                x0 = s.x_at(a)
                v0 = s.v_at(a)
                in_window = t_lo - EPS_T <= a and b <= t_hi + EPS_T
                if not in_window:
                    out.append(Segment(a, b, x0, v0, s.a))
                    continue
                if x0 >= x_max - EPS_X:
                    out.append(Segment(a, b, x_max, 0.0, 0.0))
                    continue
                t_hit = solve_crossing(a, x0, v0, s.a, x_max, a, b, direction=1)
                if t_hit is None:
                    out.append(Segment(a, b, x0, v0, s.a))
                    continue
                if t_hit > a + EPS_T:
                    out.append(Segment(a, t_hit, x0, v0, s.a))
                if t_hit < b - EPS_T:
                    out.append(Segment(t_hit, b, x_max, 0.0, 0.0))
        return Trajectory(out)

    def truncate(self, t_end: float) -> "Trajectory":
        out: list[Segment] = []
        for s in self.segments:
            if s.t0 >= t_end - EPS_T:
                break
            if s.t1 <= t_end:
                out.append(s)
            else:
                out.append(Segment(s.t0, t_end, s.x0, s.v0, s.a))
                break
        return Trajectory(out)

    def polyline(self, curve_points: int = 8) -> tuple[list[float], list[float]]:
        """Vertices for plotting: constant speed stretches are exact with two
        points, accelerated ones are subdivided to render the parabola."""
        ts: list[float] = []
        xs: list[float] = []
        for s in self.segments:
            n = 1 if abs(s.a) < 1e-12 or s.duration <= EPS_T else curve_points
            for i in range(n + 1):
                t = s.t0 + s.duration * i / n
                if ts and abs(t - ts[-1]) < EPS_T:
                    continue
                ts.append(t)
                xs.append(s.x_at(t))
        return ts, xs

    def knot_times(self) -> list[float]:
        times: list[float] = []
        for s in self.segments:
            if not times:
                times.append(s.t0)
            times.append(s.t1)
        return times

    def crossing_times(self, target: float, direction: int = 0) -> list[float]:
        """Instants at which the trajectory crosses ``target``."""
        hits: list[float] = []
        for s in self.segments:
            t = solve_crossing(s.t0, s.x0, s.v0, s.a, target, s.t0, s.t1, direction)
            if t is not None and (not hits or abs(t - hits[-1]) > 1e-6):
                hits.append(t)
        return hits


@dataclass(frozen=True)
class QuadPiece:
    """f(t) = c0 + c1*(t-t0) + c2*(t-t0)**2 valid on [t0, t1]."""

    t0: float
    t1: float
    c0: float
    c1: float
    c2: float

    def value_at(self, t: float) -> float:
        dt = t - self.t0
        return self.c0 + self.c1 * dt + self.c2 * dt * dt

    def minimum(self) -> tuple[float, float]:
        """(instant, value) of the minimum on the piece, vertex included."""
        best_t = self.t0
        best_v = self.value_at(self.t0)
        v_end = self.value_at(self.t1)
        if v_end < best_v:
            best_t, best_v = self.t1, v_end
        if self.c2 > 1e-15:
            t_vertex = self.t0 - self.c1 / (2.0 * self.c2)
            if self.t0 < t_vertex < self.t1:
                v_vertex = self.value_at(t_vertex)
                if v_vertex < best_v:
                    best_t, best_v = t_vertex, v_vertex
        return best_t, best_v

    def crossings(self, level: float) -> list[float]:
        return _quad_roots(self.c0 - level, self.c1, self.c2, self.t0, self.t1)


def _quad_roots(c0: float, c1: float, c2: float, t0: float, t1: float) -> list[float]:
    out: list[float] = []
    if abs(c2) < 1e-15:
        if abs(c1) > 1e-15:
            out.append(t0 - c0 / c1)
    else:
        disc = c1 * c1 - 4.0 * c2 * c0
        if disc >= 0.0:
            sq = math.sqrt(disc)
            out.append(t0 + (-c1 - sq) / (2.0 * c2))
            out.append(t0 + (-c1 + sq) / (2.0 * c2))
    return sorted(t for t in out if t0 - EPS_T <= t <= t1 + EPS_T)


class PiecewiseQuad:
    """Piecewise quadratic function, typically the gap between two pieces."""

    __slots__ = ("pieces",)

    def __init__(self, pieces: list[QuadPiece]) -> None:
        self.pieces = pieces

    def __bool__(self) -> bool:
        return bool(self.pieces)

    @property
    def t_start(self) -> float:
        return self.pieces[0].t0

    @property
    def t_end(self) -> float:
        return self.pieces[-1].t1

    def value_at(self, t: float) -> float:
        for p in self.pieces:
            if p.t0 - EPS_T <= t <= p.t1 + EPS_T:
                return p.value_at(t)
        if t < self.pieces[0].t0:
            return self.pieces[0].value_at(self.pieces[0].t0)
        return self.pieces[-1].value_at(self.pieces[-1].t1)

    def minimum(self) -> tuple[float, float]:
        best_t, best_v = self.pieces[0].minimum()
        for p in self.pieces[1:]:
            t, v = p.minimum()
            if v < best_v:
                best_t, best_v = t, v
        return best_t, best_v

    def first_crossing_below(self, level: float) -> float | None:
        """First instant at which the function drops below ``level``."""
        for p in self.pieces:
            if p.value_at(p.t0) < level:
                return p.t0
            for t in p.crossings(level):
                if t > p.t0 + EPS_T:
                    return t
        return None

    def polyline(self, curve_points: int = 8) -> tuple[list[float], list[float]]:
        ts: list[float] = []
        vs: list[float] = []
        for p in self.pieces:
            n = 1 if abs(p.c2) < 1e-12 else curve_points
            span = p.t1 - p.t0
            for i in range(n + 1):
                t = p.t0 + span * i / n
                if ts and abs(t - ts[-1]) < EPS_T:
                    continue
                ts.append(t)
                vs.append(p.value_at(t))
        return ts, vs


def subtract(a: Trajectory, b: Trajectory, t_lo: float, t_hi: float) -> PiecewiseQuad:
    """a(t) - b(t) as a piecewise quadratic function on [t_lo, t_hi].

    The window is narrowed to the interval where both trajectories are defined:
    outside of it the pieces do not coexist on the line.
    """
    t_lo = max(t_lo, a.t_start, b.t_start)
    t_hi = min(t_hi, a.t_end, b.t_end)
    if t_hi <= t_lo + EPS_T:
        return PiecewiseQuad([])

    bounds = {t_lo, t_hi}
    for traj in (a, b):
        for s in traj.segments:
            for t in (s.t0, s.t1):
                if t_lo < t < t_hi:
                    bounds.add(t)
    knots = sorted(bounds)

    pieces: list[QuadPiece] = []
    for lo, hi in zip(knots[:-1], knots[1:]):
        if hi - lo <= EPS_T:
            continue
        mid = 0.5 * (lo + hi)
        sa = a._find(mid)
        sb = b._find(mid)
        c0 = sa.x_at(lo) - sb.x_at(lo)
        c1 = sa.v_at(lo) - sb.v_at(lo)
        c2 = 0.5 * (sa.a - sb.a)
        pieces.append(QuadPiece(lo, hi, c0, c1, c2))
    return PiecewiseQuad(pieces)


def overlap_intervals(
    head: Trajectory,
    tail: Trajectory,
    x_lo: float,
    x_hi: float,
) -> list[tuple[float, float]]:
    """Time intervals when the piece [tail, head] overlaps [x_lo, x_hi].

    Direction independent: a reversing bar can occupy the same device twice.
    """
    if not head or not tail:
        return []
    t0 = max(head.t_start, tail.t_start)
    t1 = min(head.t_end, tail.t_end)
    if t1 <= t0 + EPS_T:
        return []
    times = {t0, t1}
    for traj in (head, tail):
        for x in (x_lo, x_hi):
            for t in traj.crossing_times(x):
                if t0 - 1e-9 <= t <= t1 + 1e-9:
                    times.add(min(max(t, t0), t1))
    ordered = sorted(times)

    def overlaps(t: float) -> bool:
        xh = head.x_at(t)
        xt = tail.x_at(t)
        lo, hi = (xt, xh) if xt <= xh else (xh, xt)
        return hi >= x_lo - 1e-9 and lo <= x_hi + 1e-9

    intervals: list[tuple[float, float]] = []
    active: float | None = None
    for ta, tb in zip(ordered[:-1], ordered[1:]):
        mid = 0.5 * (ta + tb)
        on = overlaps(mid)
        if on and active is None:
            active = ta
        elif not on and active is not None:
            if ta > active + 1e-9:
                intervals.append((active, ta))
            active = None
    if active is not None and ordered[-1] > active + 1e-9:
        intervals.append((active, ordered[-1]))
    return intervals


def interpolated_polyline(
    head: Trajectory,
    tail: Trajectory,
    fraction: float,
    curve_points: int = 8,
) -> tuple[list[float], list[float]]:
    """Geometric interpolation of the current length: 0 = tail, 1 = head.

    While the piece is free this is also the mass fraction. While stands are
    engaged it remains a geometric fraction of the visible length, not a
    reconstruction of gauge changes along the mill.
    """
    return interpolated_trajectory(head, tail, fraction).polyline(curve_points)


def interpolated_trajectory(
    head: Trajectory,
    tail: Trajectory,
    fraction: float,
) -> Trajectory:
    """Exact piecewise trajectory at a geometric fraction of a piece.

    Segment boundaries from both extremities are retained, so the interpolated
    position, velocity and acceleration are analytic on every returned segment.
    """
    fraction = min(max(fraction, 0.0), 1.0)
    if not head or not tail:
        return Trajectory()

    t_lo = max(head.t_start, tail.t_start)
    t_hi = min(head.t_end, tail.t_end)
    if t_hi <= t_lo + EPS_T:
        return Trajectory()

    bounds = {t_lo, t_hi}
    for trajectory in (head, tail):
        for segment in trajectory.segments:
            for t in (segment.t0, segment.t1):
                if t_lo < t < t_hi:
                    bounds.add(t)

    segments: list[Segment] = []
    knots = sorted(bounds)
    for lo, hi in zip(knots[:-1], knots[1:]):
        if hi <= lo + EPS_T:
            continue
        mid = 0.5 * (lo + hi)
        head_segment = head._find(mid)
        tail_segment = tail._find(mid)
        segments.append(
            Segment(
                lo,
                hi,
                (1.0 - fraction) * tail_segment.x_at(lo)
                + fraction * head_segment.x_at(lo),
                (1.0 - fraction) * tail_segment.v_at(lo)
                + fraction * head_segment.v_at(lo),
                (1.0 - fraction) * tail_segment.a + fraction * head_segment.a,
            )
        )
    return Trajectory(segments)


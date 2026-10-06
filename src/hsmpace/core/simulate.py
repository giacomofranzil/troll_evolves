"""Event-driven simulator of a piece travelling along the line.

Governing principle: **the head commands, the tail follows**.

The user describes the speed of the extremity that leads in the current
direction of travel (the material head on direct passes, the tail on reverse
passes). The speed of the other extremity follows from the mass flow balance of
the stands engaged between the two:

    v_trailing = v_leading / prod(lambda_i),  lambda_i = (h_in*w_in)/(h_out*w_out)

The discontinuities at engagement changes are both physically correct:

* at **bite** it is the trailing extremity that stays continuous (the body of
  the bar has mass and cannot change speed instantly): the leading extremity
  jumps by a factor lambda because it is gripped by the rolls;
* at **tail-out** the opposite happens, the leading extremity stays continuous
  and the trailing one jumps, because it is released by the rolls.

With a schedule consistent with the mass flow balance, the jump at bite lands
exactly on the pass speed and produces no spurious ramps.

Every commanded speed change is **anticipated**: the ramp starts early enough
for the new speed to be reached exactly at the position requested. The same
rule governs the stop before a reversal and the deceleration towards the
coiler, so there is a single semantics to remember: what you write in the input
is the point where the target is met, not where the ramp begins.

A reversing clearance is that stop position. The model derives the tail-out
speed that makes it, slowing the mill while the tail is still gripped if the
table alone cannot stop in time. The coiler slowdown is planned on the **tail**
and commanded on the leading extremity. It starts as late as possible, including
while the finishing mill is still rolling: the tail is held at the coiler
deceleration and the lead is driven at that rate times the remaining elongation
chain, so that the tail meets ``coiler_v_final`` at the mandrel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .coilbox import commanded_speed as coilbox_commanded_speed
from .coiler import (
    braking_distance,
    coiler_tail_waypoint,
    reversal_tailout_speed,
    tail_arrival_speed,
)
from .kinematics import EPS_T, Segment, Trajectory, _quad_roots, solve_crossing
from .model import (
    FWD,
    Case,
    Equipment,
    ModelError,
    Product,
    RollingPass,
    SpeedEvent,
)
from .occupancy import Occupancy, classify_working, finalise_occupancy, stamp_piece

_MAX_ITER = 200_000
_HORIZON = 2_000.0
_V_EPS = 1e-9
_X_EPS = 1e-6


@dataclass(frozen=True)
class SimEvent:
    t: float
    kind: str
    equipment_id: str = ""
    x: float = 0.0
    detail: str = ""


@dataclass(frozen=True)
class CoilboxMaterialKinematics:
    """Virtual boundaries used to reconstruct material points through a coilbox."""

    x: float
    inbound_head: Trajectory
    outbound_tail: Trajectory

    def shift(self, dt: float) -> "CoilboxMaterialKinematics":
        return CoilboxMaterialKinematics(
            self.x,
            self.inbound_head.shift(dt),
            self.outbound_tail.shift(dt),
        )


@dataclass
class PieceResult:
    """Outcome of the simulation of a single piece.

    ``head`` and ``tail`` are the **physical** trajectories, with the head
    pinned at the coiler. ``head_virtual`` is the unconstrained head, which
    keeps advancing beyond the coiler: that is the one driving the zoom rolling
    trigger, following the convention of the offline model TRoll.
    """

    piece_id: str
    product_id: str
    t_release: float
    head: Trajectory
    tail: Trajectory
    head_virtual: Trajectory
    events: tuple[SimEvent, ...] = ()
    occupancy: tuple[Occupancy, ...] = ()
    length_kinematic: float = 0.0
    length_geometric: float = 0.0
    x_coiler: float | None = None
    coiler_id: str = ""
    coilbox_material: CoilboxMaterialKinematics | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def t_start(self) -> float:
        return self.head.t_start

    @property
    def t_end(self) -> float:
        return self.head.t_end

    @property
    def length_error(self) -> float:
        if self.length_geometric == 0.0:
            return 0.0
        return 100.0 * (self.length_kinematic - self.length_geometric) / self.length_geometric

    def length_at(self, t: float) -> float:
        return self.head.x_at(t) - self.tail.x_at(t)


def _ramp_start_time(
    gap0: float,
    v_now: float,
    a_now: float,
    v_target: float,
    a_ramp: float,
    horizon: float,
) -> float | None:
    """When the remaining distance to the target point equals the ramp distance.

    ``gap0`` is the distance still to run in the direction of travel. Both the
    remaining distance and the required ramp distance are quadratic in time, so
    the instant at which they meet is found in closed form. Returns ``None``
    when it does not happen within ``horizon``, and 0.0 when it has already
    passed, meaning the ramp has to start immediately.
    """
    if a_ramp <= 0.0:
        return None
    sign = 1.0 if v_now > v_target else -1.0
    k = sign / (2.0 * a_ramp)

    c0 = gap0 - k * (v_now * v_now - v_target * v_target)
    c1 = -v_now * (1.0 + sign * a_now / a_ramp)
    c2 = -0.5 * a_now * (1.0 + sign * a_now / a_ramp)

    if c0 <= 0.0:
        return 0.0
    roots = [r for r in _quad_roots(c0, c1, c2, 0.0, horizon) if r >= 0.0]
    return roots[0] if roots else None


def simulate_piece(
    case: Case,
    product: Product,
    t_release: float = 0.0,
    piece_id: str = "P1",
    coiler: Equipment | None = None,
) -> PieceResult:
    line: Line = case.line
    settings = case.settings
    passes: list[RollingPass] = list(product.passes)
    if not passes:
        raise ModelError(f"product {product.id}: no pass defined")

    coilers = line.coilers
    if coiler is None:
        coiler = min(coilers, key=lambda e: e.x) if coilers else None
    x_coiler = coiler.x if coiler is not None else None
    x_finish = x_coiler if x_coiler is not None else line.x_max
    coiler_id = coiler.id if coiler is not None else ""
    coilbox = line.coilbox if product.uses_coilbox(line) else None
    x_cb = coilbox.x if coilbox is not None else None
    cb_arrived = False
    cb_inverted = False
    cb_tail_pinned = False
    cb_hold_until: float | None = None
    cb_overlap_warned = False
    cb_mode: str | None = None
    cb_thread_complete = False
    L_stored = 0.0
    L_paid = 0.0

    head = Trajectory()
    tail = Trajectory()
    cb_head_virtual = Trajectory()
    cb_tail_virtual = Trajectory()
    events: list[SimEvent] = []
    occupancy: list[Occupancy] = []
    warnings: list[str] = []

    t = t_release
    x_head = line.start.x
    if not settings.tunnel_furnace:
        x_head = line.start.x + 0.5 * product.slab_len
    x_tail = x_head - product.slab_len
    x_virt = x_head
    direction = FWD
    v_lead = 0.0
    lam = 1.0
    engaged: list[tuple[RollingPass, float, float]] = []
    next_idx = 0

    first = passes[0]
    nominal_target = first.approach_v if first.approach_v is not None else first.v_entry
    zoom_factor = 1.0
    ramp_accel: float | None = None
    stand_accel = line.start.accel
    armed_id: str | None = None
    armed_target = 0.0
    deferred: SpeedEvent | None = None
    reversing = False
    braking = False
    stop_target = 0.0
    stop_stand_x = 0.0
    stop_stand_id = ""
    stop_pass_no = 0
    stop_clearance = 0.0
    reverse_slowing = False
    v_star_rev: float | None = None
    coiler_braking = False
    waiting_until: float | None = None
    fired: dict[str, float] = {}

    active_events: list[SpeedEvent] = list(line.all_events())

    events.append(
        SimEvent(t, "release", line.start.id, x_head, f"slab {product.slab_len:.1f} m")
    )

    t_max = t_release + settings.max_time
    iterations = 0
    done = False

    def table_accel(x: float) -> float:
        section = line.section_at(x)
        if section is not None and section.accel:
            return section.accel
        return settings.table_accel

    def apply_coiler_command() -> None:
        nonlocal coiler_braking, ramp_accel, zoom_factor, nominal_target
        coiler_braking = True
        zoom_factor = 1.0
        a_c = coiler.accel if coiler is not None else settings.table_accel
        ramp_accel = a_c * lam
        nominal_target = settings.coiler_v_final * lam

    def pending_reversal() -> RollingPass | None:
        if not engaged or next_idx >= len(passes) or next_idx < 1:
            return None
        current = passes[next_idx - 1]
        if passes[next_idx].direction == current.direction:
            return None
        if not any(rp.pass_no == current.pass_no for rp, _x, _t in engaged):
            return None
        return current

    def emit_coiler_slowdown() -> None:
        still = "mill still rolling" if engaged else "piece free of the mill"
        events.append(
            SimEvent(
                t,
                "coiler_slowdown",
                coiler.id if coiler is not None else "",
                x_tail,
                f"target {settings.coiler_v_final:.1f} m/s at the mandrel, {still}",
            )
        )

    while not done:
        iterations += 1
        if iterations > _MAX_ITER:
            raise ModelError(f"{piece_id}: simulation does not converge (too many events)")
        if t > t_max:
            raise ModelError(
                f"{piece_id}: exceeded the maximum time of {settings.max_time:.0f} s. "
                "Check that every pass is reachable in the direction given."
            )

        if cb_hold_until is not None:
            dt = cb_hold_until - t
            if dt > EPS_T:
                head.append(Segment(t, cb_hold_until, x_head, 0.0, 0.0))
                tail.append(Segment(t, cb_hold_until, x_tail, 0.0, 0.0))
            t = cb_hold_until
            cb_hold_until = None
            # Both ends sit on the axis: the downstream extremity (kinematic
            # head) is the original tail leaving first (LIFO). Historical traces
            # are not swapped, so x_head >= x_tail holds before and after.
            x_head = x_cb or x_head
            x_tail = x_cb or x_tail
            cb_inverted = True
            cb_tail_pinned = True
            L_paid = 0.0
            direction = FWD
            lam = 1.0
            zoom_factor = 1.0
            ramp_accel = coilbox.accel if coilbox is not None else None
            v_uncoil = (
                product.coilbox_v_uncoil
                or product.coilbox_v_coil
                or product.coilbox_v_thread
            )
            if v_uncoil <= 1e-9 and next_idx < len(passes):
                nxt = passes[next_idx]
                v_uncoil = nxt.approach_v if nxt.approach_v is not None else nxt.v_entry
            nominal_target = v_uncoil if v_uncoil > 1e-9 else max(v_lead, 0.01)
            events.append(
                SimEvent(
                    t,
                    "coilbox_uncoil",
                    coilbox.id if coilbox is not None else "",
                    x_head,
                    f"original tail leaves first, {nominal_target:.2f} m/s, "
                    f"{L_stored:.1f} m stored",
                )
            )
            continue

        if waiting_until is not None:
            dt = waiting_until - t
            if dt > EPS_T:
                head.append(Segment(t, waiting_until, x_head, 0.0, 0.0))
                tail.append(Segment(t, waiting_until, x_tail, 0.0, 0.0))
            t = waiting_until
            waiting_until = None
            nxt = passes[next_idx]
            direction = nxt.direction
            nominal_target = nxt.approach_v if nxt.approach_v is not None else nxt.v_entry
            stand_accel = line.get(nxt.equipment_id).accel
            ramp_accel = None
            reversing = False
            braking = False
            reverse_slowing = False
            v_star_rev = None
            events.append(
                SimEvent(
                    t, "reverse_end", nxt.equipment_id, x_head, f"heading to pass {nxt.pass_no}"
                )
            )
            continue

        # the stand commands while the piece is gripped, the roller table when it is free
        lead_x_now = x_head if direction == FWD else x_tail
        prevailing = stand_accel if engaged else table_accel(lead_x_now)
        accel = ramp_accel if ramp_accel is not None else prevailing

        v_target = nominal_target * zoom_factor
        a_lead = 0.0
        if abs(v_target - v_lead) > _V_EPS:
            a_lead = accel if v_target > v_lead else -accel

        if direction == FWD:
            v_h, a_h = v_lead, a_lead
            v_t, a_t = v_lead / lam, a_lead / lam
            lead_x, lead_v, lead_a = x_head, v_h, a_h
            trail_x, trail_v, trail_a = x_tail, v_t, a_t
        else:
            v_h, a_h = -(v_lead / lam), -(a_lead / lam)
            v_t, a_t = -v_lead, -a_lead
            lead_x, lead_v, lead_a = x_tail, v_t, a_t
            trail_x, trail_v, trail_a = x_head, v_h, a_h

        if cb_arrived and not cb_inverted and direction == FWD and x_cb is not None:
            lead_x, lead_v, lead_a = x_cb, 0.0, 0.0
        if cb_tail_pinned and direction == FWD and x_cb is not None:
            trail_x, trail_v, trail_a = x_cb, 0.0, 0.0
            v_t, a_t = 0.0, 0.0

        if (
            coilbox is not None
            and cb_arrived
            and not cb_inverted
            and not reversing
            and not coiler_braking
        ):
            wanted = coilbox_commanded_speed(product, x_virt, x_cb or 0.0)
            if engaged:
                if wanted > 1e-9 and abs(v_lead - wanted) > 0.05 and not cb_overlap_warned:
                    warnings.append(
                        "coilbox: the rougher is still rolling the tail; the mill remains "
                        "master. Overlap with the box is not standard."
                    )
                    cb_overlap_warned = True
            elif wanted > 1e-9 and abs(nominal_target - wanted) > _V_EPS:
                nominal_target = wanted
                zoom_factor = 1.0
                ramp_accel = coilbox.accel
                entered = x_virt - x_cb
                mode = (
                    "coiling"
                    if product.coilbox_thread_length <= 1e-9
                    or entered >= product.coilbox_thread_length - 1e-9
                    else "threading"
                )
                if cb_mode != mode:
                    events.append(
                        SimEvent(
                            t,
                            "coilbox_speed",
                            coilbox.id,
                            x_cb,
                            f"{mode} {wanted:.2f} m/s",
                        )
                    )
                    cb_mode = mode
                continue

        horizon = min(t + _HORIZON, t_max)
        candidates: list[tuple[float, str, object]] = []

        # mill slowdown so tail-out speed lets the table stop exactly at clearance
        rev_pass = pending_reversal()
        if (
            rev_pass is not None
            and not reverse_slowing
            and not reversing
            and not coiler_braking
            and rev_pass.reversing_clearance > 1e-9
        ):
            x_rev = line.get(rev_pass.equipment_id).x
            a_table = table_accel(x_rev + direction * rev_pass.reversing_clearance)
            v_star = reversal_tailout_speed(rev_pass.reversing_clearance, a_table)
            a_stand = line.get(rev_pass.equipment_id).accel
            if v_star is not None and v_lead > v_star + _V_EPS and a_stand > 0.0:
                d_need = (v_lead * v_lead - v_star * v_star) / (2.0 * lam * a_stand)
                d_tail = direction * (x_rev - trail_x)
                if d_tail <= d_need + 1e-9:
                    reverse_slowing = True
                    v_star_rev = v_star
                    ramp_accel = a_stand
                    zoom_factor = 1.0
                    nominal_target = v_star
                    events.append(
                        SimEvent(
                            t,
                            "reverse_slowdown",
                            rev_pass.equipment_id,
                            trail_x,
                            f"v* {v_star:.2f} m/s at tail-out for "
                            f"{rev_pass.reversing_clearance:.1f} m clearance",
                        )
                    )
                    continue
                t_hit = solve_crossing(
                    t,
                    trail_x,
                    trail_v,
                    trail_a,
                    x_rev - direction * d_need,
                    t,
                    horizon,
                    direction,
                )
                if t_hit is not None:
                    candidates.append((t_hit, "rev_mill_brake", (v_star, a_stand, rev_pass)))

        # reversal: the piece must come to rest with the extremity closest to the
        # stand at `reversing_clearance` metres from it
        if reversing and not braking:
            d_brake = braking_distance(v_lead, 0.0, accel)
            x_brake = stop_target - direction * d_brake
            if direction * (x_brake - trail_x) <= 1e-9:
                if stop_clearance > 1e-9 and direction * (trail_x - x_brake) > _X_EPS:
                    achieved = abs(trail_x + direction * d_brake - stop_stand_x)
                    warnings.append(
                        f"pass {stop_pass_no}: {stop_clearance:.1f} m of clearance requested "
                        f"from {stop_stand_id}, {achieved:.1f} m achievable. At {v_lead:.2f} m/s "
                        f"with {accel:.2f} m/s2 the piece cannot stop any earlier, even after "
                        f"slowing the mill."
                    )
                braking = True
                nominal_target = 0.0
                continue
            t_hit = solve_crossing(
                t, trail_x, trail_v, trail_a, x_brake, t, horizon, direction
            )
            if t_hit is not None:
                candidates.append((t_hit, "brake", None))

        # deceleration towards the coiler: planned on the tail, commanded on the
        # lead. Starts as late as possible, including while the mill is still
        # rolling, so the tail meets coiler_v_final at the mandrel.
        if (
            x_coiler is not None
            and coiler is not None
            and next_idx >= len(passes)
            and not coiler_braking
            and not reversing
            and not reverse_slowing
            and direction == FWD
        ):
            x_wp, v_wp = coiler_tail_waypoint(
                trail_x, x_coiler, settings.coiler_v_final, coiler.accel, engaged
            )
            if trail_v > v_wp + _V_EPS:
                d_brake = braking_distance(trail_v, v_wp, coiler.accel)
                x_brake = x_wp - d_brake
                if trail_x >= x_brake - 1e-9:
                    arrival = tail_arrival_speed(
                        trail_x, trail_v, x_coiler, coiler.accel, engaged
                    )
                    if arrival > settings.coiler_v_final + 1e-3:
                        where = (
                            "while the mill is still rolling"
                            if engaged
                            else "within the run-out table"
                        )
                        warnings.append(
                            f"coiler: the tail cannot slow down to "
                            f"{settings.coiler_v_final:.1f} m/s {where}. "
                            f"At {coiler.accel:.2f} m/s2 it arrives at {arrival:.1f} m/s; "
                            f"{braking_distance(trail_v, v_wp, coiler.accel):.0f} m "
                            f"would be needed against the {x_wp - trail_x:.0f} m "
                            f"left to the next target."
                        )
                    apply_coiler_command()
                    emit_coiler_slowdown()
                    continue
                t_hit = solve_crossing(
                    t, trail_x, trail_v, trail_a, x_brake, t, horizon, FWD
                )
                if t_hit is not None:
                    candidates.append((t_hit, "coiler_brake", None))

        # speed events: the target must be met AT the requested position, so the
        # ramp is anticipated. Only the nearest event ahead is armed.
        # zoom rolling keeps the opposite convention on purpose: its trigger is the
        # position where the acceleration STARTS, as in the offline model TRoll
        pending = _next_event(active_events, lead_x, direction, armed_id)
        if pending is not None and pending.rel_pct:
            pending = None
        if pending is not None and not reversing and not coiler_braking and not reverse_slowing:
            gap0 = direction * (pending.x_trigger - lead_x)
            target = pending.v_target
            a_ramp = pending.accel or prevailing
            # a ramp cannot be planned across a rolling pass: the bite would reset
            # the speed anyway, so the event is left to its normal handling
            blocked = any(
                0.0 < direction * (line.get(p.equipment_id).x - lead_x)
                < direction * (pending.x_trigger - lead_x)
                for p in passes[next_idx:]
                if p.direction == direction
            )
            deferrable = not pending.during_pass and (
                blocked
                or (
                    bool(engaged)
                    and _still_engaged_at(
                        t, lead_x, lead_v, lead_a, trail_x, trail_v, trail_a,
                        pending.x_trigger, engaged, direction, horizon,
                    )
                )
            )
            if not deferrable and abs(target - v_lead) > _V_EPS:
                dt_ramp = _ramp_start_time(gap0, v_lead, a_lead, target, a_ramp, horizon - t)
                if dt_ramp is not None:
                    candidates.append((t + dt_ramp, "arm", pending))

        if a_lead != 0.0:
            candidates.append((t + (v_target - v_lead) / a_lead, "ramp", None))

        if next_idx < len(passes):
            nxt = passes[next_idx]
            x_stand = line.get(nxt.equipment_id).x
            # the stand must still be ahead: without this guard, right after a bite
            # the leading extremity sits exactly on the stand and a second pass on
            # the same stand would bite at the very same instant
            ahead = direction * (x_stand - lead_x) > _X_EPS
            blocked_by_box = (
                coilbox is not None
                and x_cb is not None
                and not cb_inverted
                and nxt.direction == FWD
                and x_stand > x_cb + _X_EPS
            )
            if nxt.direction == direction and not reversing and ahead and not blocked_by_box:
                t_hit = solve_crossing(
                    t, lead_x, lead_v, lead_a, x_stand, t, horizon, direction
                )
                if t_hit is not None:
                    candidates.append((t_hit, "bite", None))

        for i, (rp, x_stand, _t_in) in enumerate(engaged):
            t_hit = solve_crossing(
                t, trail_x, trail_v, trail_a, x_stand, t, horizon, direction
            )
            if t_hit is not None:
                candidates.append((t_hit, "tailout", i))

        for ev in active_events:
            if ev.direction != direction:
                continue
            if reversing and ev.origin == "section":
                continue
            if reverse_slowing and ev.origin == "section":
                continue
            last = fired.get(ev.id)
            t_hit = solve_crossing(
                t, lead_x, lead_v, lead_a, ev.x_trigger, t, horizon, direction
            )
            if t_hit is None:
                continue
            if last is not None and abs(t_hit - last) < 1e-6:
                continue
            candidates.append((t_hit, "trigger", ev))

        if direction == FWD and not engaged and next_idx >= len(passes):
            t_hit = solve_crossing(t, trail_x, trail_v, trail_a, x_finish, t, horizon, FWD)
            if t_hit is not None:
                candidates.append((t_hit, "finish", None))

        if coilbox is not None and x_cb is not None and direction == FWD:
            if not cb_arrived:
                t_hit = solve_crossing(t, x_head, v_h, a_h, x_cb, t, horizon, FWD)
                if t_hit is not None:
                    candidates.append((t_hit, "cb_arrive", None))
            elif not cb_inverted:
                t_hit = solve_crossing(t, x_tail, v_t, a_t, x_cb, t, horizon, FWD)
                if t_hit is not None:
                    candidates.append((t_hit, "cb_full", None))
                if product.coilbox_thread_length > 1e-9 and not cb_thread_complete:
                    target_virt = x_cb + product.coilbox_thread_length
                    if x_virt + _X_EPS < target_virt:
                        t_hit = solve_crossing(
                            t, x_virt, v_h, a_h, target_virt, t, horizon, FWD
                        )
                        if t_hit is not None:
                            candidates.append((t_hit, "cb_thread_done", None))
            elif cb_tail_pinned:
                # Stored length is transfer-bar metres. Metal leaves the box at
                # mill entry speed v_lead/lambda, not at head speed: F1 can bite
                # while the tail is still in the box.
                v_box = v_lead / lam
                a_box = a_lead / lam
                if L_paid + 1e-9 < L_stored:
                    t_hit = solve_crossing(
                        t, L_paid, v_box, a_box, L_stored, t, horizon, FWD
                    )
                    if t_hit is not None:
                        candidates.append((t_hit, "cb_unpin", None))

        if not candidates:
            if next_idx < len(passes):
                nxt = passes[next_idx]
                heading = "fwd" if nxt.direction == FWD else "rev"
                raise ModelError(
                    f"{piece_id}: pass {nxt.pass_no} on {nxt.equipment_id} is not reachable "
                    f"in direction {heading}. At t={t:.1f} s the piece spans "
                    f"[{x_tail:.1f}, {x_head:.1f}] m and the stand is at "
                    f"{line.get(nxt.equipment_id).x:.1f} m."
                )
            raise ModelError(
                f"{piece_id}: the piece stopped at x={x_head:.1f} m with no further events. "
                "A speed command is missing at the end of the route."
            )

        t_next, action, payload = min(candidates, key=lambda c: (c[0], c[1]))
        dt = max(t_next - t, 0.0)

        if dt > EPS_T:
            if cb_arrived and not cb_inverted and x_cb is not None:
                head.append(Segment(t, t_next, x_cb, 0.0, 0.0))
                tail.append(Segment(t, t_next, x_tail, v_t, a_t))
                cb_head_virtual.append(Segment(t, t_next, x_virt, v_h, a_h))
                x_virt = x_virt + v_h * dt + 0.5 * a_h * dt * dt
                x_tail = x_tail + v_t * dt + 0.5 * a_t * dt * dt
                x_head = x_cb
            elif cb_tail_pinned and x_cb is not None:
                head.append(Segment(t, t_next, x_head, v_h, a_h))
                tail.append(Segment(t, t_next, x_cb, 0.0, 0.0))
                cb_tail_virtual.append(
                    Segment(
                        t,
                        t_next,
                        x_cb + L_paid - L_stored,
                        v_lead / lam,
                        a_lead / lam,
                    )
                )
                x_head = x_head + v_h * dt + 0.5 * a_h * dt * dt
                x_tail = x_cb
                L_paid += (v_lead / lam) * dt + 0.5 * (a_lead / lam) * dt * dt
            else:
                head.append(Segment(t, t_next, x_head, v_h, a_h))
                tail.append(Segment(t, t_next, x_tail, v_t, a_t))
                x_head = x_head + v_h * dt + 0.5 * a_h * dt * dt
                x_tail = x_tail + v_t * dt + 0.5 * a_t * dt * dt
            v_lead = max(v_lead + a_lead * dt, 0.0)
            t = t_next

        if action == "brake":
            braking = True
            nominal_target = 0.0
            continue

        if action == "rev_mill_brake":
            v_star, a_stand, rp_rev = payload  # type: ignore[misc]
            reverse_slowing = True
            v_star_rev = float(v_star)
            ramp_accel = float(a_stand)
            zoom_factor = 1.0
            nominal_target = float(v_star)
            events.append(
                SimEvent(
                    t,
                    "reverse_slowdown",
                    rp_rev.equipment_id,
                    trail_x,
                    f"v* {v_star_rev:.2f} m/s at tail-out for "
                    f"{rp_rev.reversing_clearance:.1f} m clearance",
                )
            )
            continue

        if action == "coiler_brake":
            apply_coiler_command()
            emit_coiler_slowdown()
            continue

        if action == "cb_arrive":
            cb_arrived = True
            x_virt = max(x_head, x_cb or x_head)
            x_head = x_cb or x_head
            events.append(
                SimEvent(
                    t,
                    "coilbox_in",
                    coilbox.id if coilbox is not None else "",
                    x_head,
                    "head enters the coilbox",
                )
            )
            continue

        if action == "cb_thread_done":
            cb_thread_complete = True
            continue

        if action == "cb_full":
            x_tail = x_cb or x_tail
            L_stored = max(x_virt - (x_cb or x_virt), 1e-6)
            v_lead = 0.0
            nominal_target = 0.0
            zoom_factor = 1.0
            delay = product.coilbox_delay
            cb_hold_until = t + delay
            events.append(
                SimEvent(
                    t,
                    "coilbox_full",
                    coilbox.id if coilbox is not None else "",
                    x_tail,
                    f"{L_stored:.1f} m stored, hold {delay:.1f} s",
                )
            )
            continue

        if action == "cb_unpin":
            cb_tail_pinned = False
            x_tail = x_cb or x_tail
            events.append(
                SimEvent(
                    t,
                    "coilbox_empty",
                    coilbox.id if coilbox is not None else "",
                    x_tail,
                    "last metal leaves the coilbox",
                )
            )
            continue

        if action == "arm":
            ev: SpeedEvent = payload  # type: ignore[assignment]
            armed_id = ev.id
            nominal_target = ev.v_target
            zoom_factor = 1.0
            armed_target = nominal_target
            ramp_accel = ev.accel
            if engaged:
                warnings.append(
                    f"section event {ev.id}: to reach {armed_target:.2f} m/s at "
                    f"x={ev.x_trigger:.1f} m the ramp has to start while the piece is still "
                    "being rolled, so the mill speed changes during the pass."
                )
            continue

        if action == "ramp":
            v_lead = v_target
            if not coiler_braking:
                ramp_accel = None
            if braking and v_target <= _V_EPS:
                rp_prev = _last_completed_pass(passes, next_idx)
                waiting_until = t + (rp_prev.reversing_delay if rp_prev else 0.0)
                events.append(
                    SimEvent(
                        t,
                        "reverse_wait",
                        stop_stand_id,
                        x_head,
                        f"reversing delay {rp_prev.reversing_delay:.1f} s" if rp_prev else "",
                    )
                )
            continue

        if action == "bite":
            rp = passes[next_idx]
            eq = line.get(rp.equipment_id)
            lam *= rp.elongation
            v_lead *= rp.elongation
            engaged.append((rp, eq.x, t))
            nominal_target = rp.v_exit
            stand_accel = eq.accel
            ramp_accel = None
            armed_id = None
            next_idx += 1
            events.append(
                SimEvent(
                    t,
                    "bite",
                    eq.id,
                    eq.x,
                    f"pass {rp.pass_no}: {rp.h_in:.1f} -> {rp.h_out:.1f} mm, "
                    f"lambda {rp.elongation:.3f}, v_exit {rp.v_exit:.2f} m/s",
                )
            )
            if rp.zoom_pct:
                active_events.append(
                    SpeedEvent(
                        id=f"zoom-{product.id}-{rp.pass_no}",
                        section_id="",
                        x_trigger=eq.x + rp.zoom_trigger,
                        accel=rp.zoom_accel,
                        direction=FWD,
                        during_pass=True,
                        origin="zoom",
                        rel_pct=rp.zoom_pct,
                    )
                )
            continue

        if action == "tailout":
            idx = int(payload)  # type: ignore[arg-type]
            rp, x_stand, t_in = engaged.pop(idx)
            lam /= rp.elongation
            occupancy.append(Occupancy(rp.equipment_id, rp.pass_no, t_in, t))
            v_star_here = v_star_rev
            if v_star_here is None and rp.reversing_clearance > 1e-9:
                v_star_here = reversal_tailout_speed(
                    rp.reversing_clearance,
                    table_accel(x_stand + direction * rp.reversing_clearance),
                )
            if v_star_here is not None:
                detail = (
                    f"pass {rp.pass_no}: tail-out {v_lead:.2f} m/s "
                    f"(v* {v_star_here:.2f} m/s for {rp.reversing_clearance:.1f} m clearance)"
                )
            else:
                detail = f"pass {rp.pass_no}"
            events.append(SimEvent(t, "tail_out", rp.equipment_id, x_stand, detail))
            if coiler_braking:
                apply_coiler_command()
            if not engaged:
                if deferred is not None and not coiler_braking:
                    pendingev, deferred = deferred, None
                    if pendingev.rel_pct:
                        zoom_factor *= 1.0 + pendingev.rel_pct / 100.0
                    else:
                        nominal_target = pendingev.v_target
                    ramp_accel = pendingev.accel
                    events.append(
                        SimEvent(
                            t,
                            "speed_change",
                            pendingev.section_id,
                            x_head,
                            f"{pendingev.v_target:.2f} m/s (deferred to disengagement)",
                        )
                    )
                if next_idx < len(passes) and passes[next_idx].direction != direction:
                    reversing = True
                    braking = False
                    zoom_factor = 1.0
                    ramp_accel = None
                    armed_id = None
                    reverse_slowing = False
                    # the clearance belongs to the pass the reversal comes after
                    stop_stand_x = x_stand
                    stop_stand_id = rp.equipment_id
                    stop_pass_no = rp.pass_no
                    stop_clearance = rp.reversing_clearance
                    stop_target = x_stand + direction * stop_clearance
                    a_table = table_accel(stop_target)
                    v_star_rev = reversal_tailout_speed(stop_clearance, a_table)
                    if v_star_rev is not None:
                        detail = (
                            f"clearance {stop_clearance:.1f} m, v* {v_star_rev:.2f} m/s, "
                            f"tail-out {v_lead:.2f} m/s"
                        )
                    elif stop_clearance:
                        detail = f"clearance requested {stop_clearance:.1f} m"
                    else:
                        detail = "stopping at the shortest braking distance"
                    events.append(
                        SimEvent(t, "reverse_start", rp.equipment_id, x_stand, detail)
                    )
                    if v_star_rev is not None and v_lead > v_star_rev + 0.05:
                        warnings.append(
                            f"pass {rp.pass_no}: v* {v_star_rev:.2f} m/s needed at tail-out "
                            f"for {stop_clearance:.1f} m clearance, {v_lead:.2f} m/s reached"
                        )
                    if v_lead <= _V_EPS and stop_clearance <= 1e-9:
                        braking = True
                        waiting_until = t + rp.reversing_delay
            continue

        if action == "trigger":
            trig: SpeedEvent = payload  # type: ignore[assignment]
            fired[trig.id] = t
            # zoom is commanded on the virtual head and must not depend on which
            # coiler takes the strip; other section events stay suppressed
            if (coiler_braking or reverse_slowing) and not trig.rel_pct:
                continue
            if engaged and not trig.during_pass:
                deferred = trig
                armed_id = None
                continue
            anticipated = armed_id == trig.id
            if anticipated:
                armed_id = None
                if abs(v_lead - armed_target) > max(0.02 * max(armed_target, 1.0), 0.05):
                    warnings.append(
                        f"section event {trig.id}: {armed_target:.2f} m/s requested at "
                        f"x={trig.x_trigger:.1f} m, {v_lead:.2f} m/s reached. Not enough "
                        "distance to complete the ramp."
                    )
            else:
                # never armed, for example because the piece was already at speed
                if trig.rel_pct:
                    zoom_factor *= 1.0 + trig.rel_pct / 100.0
                else:
                    nominal_target = trig.v_target
                    zoom_factor = 1.0
                if trig.accel is not None:
                    ramp_accel = trig.accel
            kind = "zoom" if trig.rel_pct else "speed_change"
            if trig.rel_pct:
                detail = f"zoom {trig.rel_pct:+.1f}% on the virtual head"
            elif anticipated:
                detail = f"{trig.v_target:.2f} m/s reached here as requested"
            else:
                detail = f"{trig.v_target:.2f} m/s commanded from here"
            events.append(SimEvent(t, kind, trig.section_id, trig.x_trigger, detail))
            continue

        if action == "finish":
            events.append(SimEvent(t, "coiling_end", "", x_finish, "tail at the coiler"))
            done = True
            continue

        raise ModelError(f"unknown action: {action}")

    head_virtual = head
    if x_coiler is not None:
        head_phys = head.clamp_max(x_coiler)
        tail_phys = tail.clamp_max(x_coiler)
        t_coil = head.crossing_times(x_coiler, direction=FWD)
        if t_coil:
            events.append(SimEvent(t_coil[0], "coiling_start", "", x_coiler, "gripped by mandrel"))
    else:
        head_phys = head
        tail_phys = tail

    length_kin = head_virtual.x_at(head_virtual.t_end) - tail.x_at(tail.t_end)
    length_geo = product.final_length
    if abs(length_kin - length_geo) > max(0.01 * length_geo, 0.05):
        warnings.append(
            f"kinematic length {length_kin:.1f} m against {length_geo:.1f} m geometric: "
            "mass balance is not conserved"
        )

    events.sort(key=lambda e: e.t)
    return PieceResult(
        piece_id=piece_id,
        product_id=product.id,
        t_release=t_release,
        head=head_phys,
        tail=tail_phys,
        head_virtual=head_virtual,
        events=tuple(events),
        occupancy=classify_working(
            stamp_piece(
                finalise_occupancy(line, head_phys, tail_phys, occupancy), piece_id
            ),
            line,
            coiler_id,
        ),
        length_kinematic=length_kin,
        length_geometric=length_geo,
        x_coiler=x_coiler,
        coiler_id=coiler_id,
        coilbox_material=(
            CoilboxMaterialKinematics(x_cb, cb_head_virtual, cb_tail_virtual)
            if x_cb is not None and cb_head_virtual and cb_tail_virtual
            else None
        ),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _next_event(
    active_events: list[SpeedEvent],
    lead_x: float,
    direction: int,
    armed_id: str | None,
) -> SpeedEvent | None:
    """Nearest event still ahead in the current direction of travel."""
    best: SpeedEvent | None = None
    best_gap = float("inf")
    for ev in active_events:
        if ev.direction != direction or ev.id == armed_id:
            continue
        gap = direction * (ev.x_trigger - lead_x)
        if gap > _X_EPS and gap < best_gap:
            best, best_gap = ev, gap
    return best


def _still_engaged_at(
    t: float,
    lead_x: float,
    lead_v: float,
    lead_a: float,
    trail_x: float,
    trail_v: float,
    trail_a: float,
    x_trigger: float,
    engaged: list[tuple[RollingPass, float, float]],
    direction: int,
    horizon: float,
) -> bool:
    """Whether the piece will still be rolling when the target position is reached.

    Anticipating a ramp that ends inside the rolling zone would let a roller
    table setpoint override the pass speed halfway through the pass, so in that
    case the event stays deferred to disengagement as usual. The estimate uses
    the current law of motion, which is enough to tell the two situations apart.
    """
    t_trigger = solve_crossing(t, lead_x, lead_v, lead_a, x_trigger, t, horizon, direction)
    if t_trigger is None:
        return True
    for _rp, x_stand, _t_in in engaged:
        t_out = solve_crossing(t, trail_x, trail_v, trail_a, x_stand, t, horizon, direction)
        if t_out is None or t_out > t_trigger:
            return True
    return False


def _last_completed_pass(passes: list[RollingPass], next_idx: int) -> RollingPass | None:
    return passes[next_idx - 1] if 0 < next_idx <= len(passes) else None


def simulate_case(case: Case) -> list[PieceResult]:
    """Simulate the sequence of pieces defined in the settings.

    In open-loop mode the pieces are independent: every product is simulated
    once and the copies are shifted in time.
    """
    pacing = case.settings.pacing
    cache: dict[tuple[str, str], PieceResult] = {}
    out: list[PieceResult] = []
    for i, product_id in enumerate(case.piece_products):
        assigned = case.coiler_for_index(i)
        key = (product_id, assigned.id if assigned is not None else "")
        base = cache.get(key)
        if base is None:
            base = simulate_piece(
                case, case.product(product_id), 0.0, product_id, coiler=assigned
            )
            cache[key] = base
        out.append(shift_result(base, i * pacing, f"#{i + 1}"))
    return out


def shift_result(result: PieceResult, dt: float, piece_id: str | None = None) -> PieceResult:
    return PieceResult(
        piece_id=piece_id or result.piece_id,
        product_id=result.product_id,
        t_release=result.t_release + dt,
        head=result.head.shift(dt),
        tail=result.tail.shift(dt),
        head_virtual=result.head_virtual.shift(dt),
        events=tuple(
            SimEvent(e.t + dt, e.kind, e.equipment_id, e.x, e.detail) for e in result.events
        ),
        occupancy=tuple(
            Occupancy(
                o.equipment_id,
                o.pass_no,
                o.t_in + dt,
                o.t_out + dt,
                piece_id=piece_id or result.piece_id,
                working=o.working,
            )
            for o in result.occupancy
        ),
        length_kinematic=result.length_kinematic,
        length_geometric=result.length_geometric,
        x_coiler=result.x_coiler,
        coiler_id=result.coiler_id,
        coilbox_material=(
            result.coilbox_material.shift(dt)
            if result.coilbox_material is not None
            else None
        ),
        warnings=result.warnings,
    )

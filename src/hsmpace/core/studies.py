"""Pacing studies: gap versus pacing curve, minimum pacing, robustness.

In open-loop mode the pieces are decoupled: every product is simulated once and
the copies are obtained by shifting the trajectories in time. This makes it
negligible to scan hundreds of pacing values or to run thousands of Monte Carlo
draws.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from .analysis import GapAnalysis, analyse_sequence
from .model import Case, Product, harmonise_tandem_speeds
from .simulate import PieceResult, shift_result, simulate_piece


def base_results(case: Case) -> dict[tuple[str, str], PieceResult]:
    """One simulation per (product, coiler) pair that the sequence can request.

    The cache is the cartesian product of the products in the case and the
    coilers in the cycle in force (``coiler_pattern``, or every coiler when it
    is empty). That way the number of pieces and the product of each piece can
    change later, as the UI does, without missing a pairing.
    """
    out: dict[tuple[str, str], PieceResult] = {}
    coiler_ids = list(dict.fromkeys(case.coiler_cycle)) or [""]
    for product in case.products:
        for cid in coiler_ids:
            assigned = case.line.get(cid) if cid else None
            out[(product.id, cid)] = simulate_piece(
                case, product, 0.0, product.id, coiler=assigned
            )
    return out


def sequence(
    case: Case,
    base: dict[tuple[str, str], PieceResult],
    pacing: float,
    jitter: list[float] | None = None,
) -> list[PieceResult]:
    out: list[PieceResult] = []
    for i, product_id in enumerate(case.piece_products):
        assigned = case.coiler_for_index(i)
        key = (product_id, assigned.id if assigned is not None else "")
        offset = i * pacing + (jitter[i] if jitter else 0.0)
        out.append(shift_result(base[key], offset, f"#{i + 1}"))
    return out


@dataclass(frozen=True)
class PacingPoint:
    pacing: float
    min_gap: float
    feasible: bool
    t_critical: float | None = None
    x_critical: float | None = None
    section: str = ""
    equipment: str = ""
    pair: str = ""


def _point(case: Case, analyses: list[GapAnalysis], pacing: float) -> PacingPoint:
    gap_min = case.settings.gap_min
    if not analyses:
        return PacingPoint(pacing, float("inf"), True)
    worst = min(analyses, key=lambda a: a.min_gap)
    c = worst.critical
    return PacingPoint(
        pacing=pacing,
        min_gap=worst.min_gap,
        feasible=worst.min_gap >= gap_min,
        t_critical=c.t if c else None,
        x_critical=c.x if c else None,
        section=c.section if c else "",
        equipment=c.equipment if c else "",
        pair=f"{worst.front_id} / {worst.rear_id}",
    )


def gap_vs_pacing(
    case: Case,
    base: dict[tuple[str, str], PieceResult] | None = None,
    pacings: list[float] | None = None,
) -> list[PacingPoint]:
    """Minimum gap of the sequence as a function of the pacing.

    This is the most useful chart of the tool: the minimum feasible pacing is
    read where the curve crosses the threshold, and the distance from the
    threshold is the margin being worked with.
    """
    base = base or base_results(case)
    if pacings is None:
        s = case.settings
        steps = max(2, s.pacing_scan_steps)
        span = s.pacing_scan_max - s.pacing_scan_min
        pacings = [s.pacing_scan_min + span * i / (steps - 1) for i in range(steps)]

    out: list[PacingPoint] = []
    for pacing in pacings:
        results = sequence(case, base, pacing)
        analyses = analyse_sequence(results, case.settings.gap_min, case.line)
        out.append(_point(case, analyses, pacing))
    return out


def min_feasible_pacing(
    case: Case,
    base: dict[tuple[str, str], PieceResult] | None = None,
    curve: list[PacingPoint] | None = None,
    tolerance: float = 0.1,
) -> PacingPoint | None:
    """Smallest pacing beyond which the sequence always stays feasible.

    With reverse passes the minimum gap is not monotonic in the pacing, so a
    blind bisection does not apply: the curve is scanned, the last infeasible
    point is taken and the interval right after it is refined.
    """
    base = base or base_results(case)
    curve = curve or gap_vs_pacing(case, base)
    if not curve:
        return None

    last_bad = None
    for point in curve:
        if not point.feasible:
            last_bad = point
    if last_bad is None:
        return curve[0]

    after = [p for p in curve if p.pacing > last_bad.pacing]
    if not after:
        return None

    lo, hi = last_bad.pacing, after[0].pacing
    while hi - lo > tolerance:
        mid = 0.5 * (lo + hi)
        analyses = analyse_sequence(
            sequence(case, base, mid), case.settings.gap_min, case.line
        )
        point = _point(case, analyses, mid)
        if point.feasible:
            hi = mid
        else:
            lo = mid

    analyses = analyse_sequence(sequence(case, base, hi), case.settings.gap_min, case.line)
    return _point(case, analyses, hi)


@dataclass(frozen=True)
class MonteCarloResult:
    runs: int
    pacing: float
    violations: int
    min_gaps: tuple[float, ...]
    errors: int = 0

    @property
    def violation_rate(self) -> float:
        return self.violations / self.runs if self.runs else 0.0

    def percentile(self, q: float) -> float:
        if not self.min_gaps:
            return float("nan")
        data = sorted(self.min_gaps)
        idx = min(len(data) - 1, max(0, int(round(q * (len(data) - 1)))))
        return data[idx]

    @property
    def mean(self) -> float:
        return sum(self.min_gaps) / len(self.min_gaps) if self.min_gaps else float("nan")


def perturb_case(case: Case, rng: random.Random) -> Case:
    """Perturb pass speeds and dead times.

    Speeds are perturbed before the mass flow balance, so that in the tandem
    only the perturbation of the master stand matters and the schedule stays
    physical.
    """
    tol = case.settings.mc_speed_tol_pct / 100.0
    sigma = case.settings.mc_delay_sigma

    products: list[Product] = []
    for product in case.products:
        passes = []
        for rp in product.passes:
            factor = 1.0 + rng.uniform(-tol, tol)
            delay = max(0.0, rp.reversing_delay + rng.gauss(0.0, sigma))
            passes.append(replace(rp, v_exit=rp.v_exit * factor, reversing_delay=delay))
        products.append(replace(product, passes=tuple(passes)))

    perturbed = replace(case, products=tuple(products))
    harmonised, _ = harmonise_tandem_speeds(perturbed)
    return harmonised


def monte_carlo(
    case: Case,
    pacing: float | None = None,
    runs: int | None = None,
    seed: int | None = None,
) -> MonteCarloResult:
    """Probability of violating the gap with dispersed speeds and dead times.

    Every piece gets its own independent perturbation and a jitter on the
    release instant: the nominal pacing is never met to the second.
    """
    settings = case.settings
    pacing = settings.pacing if pacing is None else pacing
    runs = settings.mc_runs if runs is None else runs
    rng = random.Random(settings.mc_seed if seed is None else seed)

    min_gaps: list[float] = []
    violations = 0
    errors = 0

    for _ in range(runs):
        try:
            results: list[PieceResult] = []
            for i, product_id in enumerate(case.piece_products):
                perturbed = perturb_case(case, rng)
                offset = i * pacing + rng.gauss(0.0, settings.mc_release_sigma)
                res = simulate_piece(
                    perturbed,
                    perturbed.product(product_id),
                    offset,
                    f"#{i + 1}",
                    coiler=case.coiler_for_index(i),
                )
                results.append(res)
            analyses = analyse_sequence(results, settings.gap_min, case.line)
        except Exception:  # extreme inputs produced by the sampling
            errors += 1
            continue

        if not analyses:
            min_gaps.append(float("inf"))
            continue
        worst = min(a.min_gap for a in analyses)
        min_gaps.append(worst)
        if worst < settings.gap_min:
            violations += 1

    return MonteCarloResult(
        runs=len(min_gaps),
        pacing=pacing,
        violations=violations,
        min_gaps=tuple(min_gaps),
        errors=errors,
    )

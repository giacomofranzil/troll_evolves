"""JSON contract for the input and output of the calculation core.

This is the surface a Level 2 system written in C++ or C# can use right away by
invoking the executable, and the specification to honour when the core is
rewritten in those languages. See docs/algorithm-spec.md.
"""

from __future__ import annotations

from typing import Any

from .analysis import GapAnalysis
from .model import (
    FWD,
    REV,
    MILL_HSM,
    Case,
    Equipment,
    Line,
    MassFlowDeviation,
    Product,
    RollingPass,
    Section,
    SimSettings,
    SpeedEvent,
    UtilityRecipe,
    WHEN_OCCUPY,
)
from .simulate import PieceResult
from .studies import MonteCarloResult, PacingPoint
from .utilities import analyse_utilities

CONTRACT_VERSION = "1"


def _direction_out(value: int) -> str:
    return "fwd" if value == FWD else "rev"


def _direction_in(value: Any) -> int:
    return REV if str(value).lower() in {"rev", "-1", "indietro"} else FWD


_MISSING = object()


def _optional_flag(value: Any) -> bool | None:
    if value is _MISSING or value is None or value == "":
        return None
    return bool(value)


def case_to_dict(case: Case) -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "mill_type": case.mill_type,
        "info": dict(case.info),
        "layout": [
            {
                "id": e.id,
                "kind": e.kind,
                "x_m": e.x,
                "accel_mps2": e.accel,
                "group": e.group,
                "label": e.label,
                "occupy": e.occupy,
                "occupy_before_m": e.occupy_before,
                "occupy_after_m": e.occupy_after,
            }
            for e in case.line.equipment
        ],
        "sections": [
            {
                "id": s.id,
                "label": s.label,
                "x_start_m": s.x_start,
                "length_m": s.length,
                "accel_mps2": s.accel,
                "events": [
                    {
                        "id": ev.id,
                        "x_trigger_m": ev.x_trigger,
                        "v_target_mps": ev.v_target,
                        "accel_mps2": ev.accel,
                        "direction": _direction_out(ev.direction),
                        "during_pass": ev.during_pass,
                        "rel_pct": ev.rel_pct,
                    }
                    for ev in s.events
                ],
            }
            for s in case.line.sections
        ],
        "products": [
            {
                "id": p.id,
                "label": p.label,
                "grade": p.grade,
                "slab_thk_mm": p.slab_thk,
                "slab_wid_mm": p.slab_wid,
                "slab_len_m": p.slab_len,
                "use_coilbox": p.use_coilbox,
                "coilbox_v_thread_mps": p.coilbox_v_thread,
                "coilbox_v_coil_mps": p.coilbox_v_coil,
                "coilbox_v_uncoil_mps": p.coilbox_v_uncoil,
                "coilbox_thread_length_m": p.coilbox_thread_length,
                "coilbox_delay_s": p.coilbox_delay,
                "passes": [
                    {
                        "pass_no": rp.pass_no,
                        "equipment_id": rp.equipment_id,
                        "direction": _direction_out(rp.direction),
                        "h_in_mm": rp.h_in,
                        "h_out_mm": rp.h_out,
                        "w_in_mm": rp.w_in,
                        "w_out_mm": rp.w_out,
                        "v_exit_mps": rp.v_exit,
                        "reversing_delay_s": rp.reversing_delay,
                        "reversing_clearance_m": rp.reversing_clearance,
                        "approach_v_mps": rp.approach_v,
                        "master": rp.master,
                        "zoom_pct": rp.zoom_pct,
                        "zoom_trigger_m": rp.zoom_trigger,
                        "zoom_accel_mps2": rp.zoom_accel,
                    }
                    for rp in p.passes
                ],
            }
            for p in case.products
        ],
        "settings": {
            "pacing_s": case.settings.pacing,
            "n_pieces": case.settings.n_pieces,
            "piece_products": list(case.settings.piece_products),
            "coiler_pattern": list(case.settings.coiler_pattern),
            "gap_min_m": case.settings.gap_min,
            "pacing_scan_min_s": case.settings.pacing_scan_min,
            "pacing_scan_max_s": case.settings.pacing_scan_max,
            "pacing_scan_steps": case.settings.pacing_scan_steps,
            "mc_runs": case.settings.mc_runs,
            "mc_speed_tol_pct": case.settings.mc_speed_tol_pct,
            "mc_delay_sigma_s": case.settings.mc_delay_sigma,
            "mc_release_sigma_s": case.settings.mc_release_sigma,
            "mc_seed": case.settings.mc_seed,
            "table_accel_mps2": case.settings.table_accel,
            "coiler_v_final_mps": case.settings.coiler_v_final,
            "max_time_s": case.settings.max_time,
            "time_axis_down": case.settings.time_axis_down,
        },
        "utilities": [
            {
                "equipment_id": u.equipment_id,
                "utility": u.utility,
                "rate": u.rate,
                "when": u.when,
            }
            for u in case.utilities
        ],
    }


def case_from_dict(data: dict) -> Case:
    equipment = tuple(
        Equipment(
            id=e["id"],
            kind=e.get("kind", "marker"),
            x=float(e["x_m"]),
            accel=float(e.get("accel_mps2", 1.0)),
            group=e.get("group", ""),
            label=e.get("label", ""),
            occupy=e.get("occupy"),
            occupy_before=float(e.get("occupy_before_m", 0.0) or 0.0),
            occupy_after=float(e.get("occupy_after_m", 0.0) or 0.0),
        )
        for e in data.get("layout", [])
    )

    sections = []
    for s in data.get("sections", []):
        events = tuple(
            SpeedEvent(
                id=ev.get("id", f"{s['id']}-{i + 1}"),
                section_id=s["id"],
                x_trigger=float(ev["x_trigger_m"]),
                v_target=float(ev.get("v_target_mps", 0.0)),
                accel=ev.get("accel_mps2"),
                direction=_direction_in(ev.get("direction", "fwd")),
                during_pass=bool(ev.get("during_pass", False)),
                rel_pct=float(ev.get("rel_pct", 0.0)),
            )
            for i, ev in enumerate(s.get("events", []))
        )
        sections.append(
            Section(
                id=s["id"],
                x_start=float(s["x_start_m"]),
                length=float(s["length_m"]),
                label=s.get("label", ""),
                accel=s.get("accel_mps2"),
                events=events,
            )
        )

    products = []
    for p in data.get("products", []):
        passes = tuple(
            RollingPass(
                product_id=p["id"],
                pass_no=int(rp["pass_no"]),
                equipment_id=rp["equipment_id"],
                direction=_direction_in(rp.get("direction", "fwd")),
                h_in=float(rp["h_in_mm"]),
                h_out=float(rp["h_out_mm"]),
                w_in=float(rp["w_in_mm"]),
                w_out=float(rp["w_out_mm"]),
                v_exit=float(rp["v_exit_mps"]),
                reversing_delay=float(rp.get("reversing_delay_s", 0.0)),
                reversing_clearance=float(rp.get("reversing_clearance_m", 0.0)),
                approach_v=rp.get("approach_v_mps"),
                master=bool(rp.get("master", False)),
                zoom_pct=float(rp.get("zoom_pct", 0.0)),
                zoom_trigger=float(rp.get("zoom_trigger_m", 0.0)),
                zoom_accel=rp.get("zoom_accel_mps2"),
            )
            for rp in p.get("passes", [])
        )
        products.append(
            Product(
                id=p["id"],
                slab_thk=float(p["slab_thk_mm"]),
                slab_wid=float(p["slab_wid_mm"]),
                slab_len=float(p["slab_len_m"]),
                label=p.get("label", ""),
                grade=p.get("grade", ""),
                passes=passes,
                use_coilbox=_optional_flag(p.get("use_coilbox", p.get("coilbox", _MISSING))),
                coilbox_v_thread=float(p.get("coilbox_v_thread_mps", 0.0) or 0.0),
                coilbox_v_coil=float(p.get("coilbox_v_coil_mps", 0.0) or 0.0),
                coilbox_v_uncoil=float(p.get("coilbox_v_uncoil_mps", 0.0) or 0.0),
                coilbox_thread_length=float(p.get("coilbox_thread_length_m", 0.0) or 0.0),
                coilbox_delay=float(p.get("coilbox_delay_s", 0.0) or 0.0),
            )
        )

    raw = data.get("settings", {})
    defaults = SimSettings()
    settings = SimSettings(
        pacing=float(raw.get("pacing_s", defaults.pacing)),
        n_pieces=int(raw.get("n_pieces", defaults.n_pieces)),
        piece_products=tuple(raw.get("piece_products", ())),
        coiler_pattern=tuple(raw.get("coiler_pattern", ())),
        gap_min=float(raw.get("gap_min_m", defaults.gap_min)),
        pacing_scan_min=float(raw.get("pacing_scan_min_s", defaults.pacing_scan_min)),
        pacing_scan_max=float(raw.get("pacing_scan_max_s", defaults.pacing_scan_max)),
        pacing_scan_steps=int(raw.get("pacing_scan_steps", defaults.pacing_scan_steps)),
        mc_runs=int(raw.get("mc_runs", defaults.mc_runs)),
        mc_speed_tol_pct=float(raw.get("mc_speed_tol_pct", defaults.mc_speed_tol_pct)),
        mc_delay_sigma=float(raw.get("mc_delay_sigma_s", defaults.mc_delay_sigma)),
        mc_release_sigma=float(raw.get("mc_release_sigma_s", defaults.mc_release_sigma)),
        mc_seed=int(raw.get("mc_seed", defaults.mc_seed)),
        table_accel=float(raw.get("table_accel_mps2", defaults.table_accel)),
        coiler_v_final=float(raw.get("coiler_v_final_mps", defaults.coiler_v_final)),
        max_time=float(raw.get("max_time_s", defaults.max_time)),
        time_axis_down=bool(raw.get("time_axis_down", defaults.time_axis_down)),
    )

    utilities = tuple(
        UtilityRecipe(
            equipment_id=str(u["equipment_id"]),
            utility=str(u.get("utility", "")).lower(),
            rate=float(u.get("rate", 0.0) or 0.0),
            when=str(u.get("when") or WHEN_OCCUPY).lower(),
        )
        for u in data.get("utilities", [])
    )

    return Case(
        line=Line(equipment, tuple(sections)),
        products=tuple(products),
        settings=settings,
        mill_type=str(data.get("mill_type") or data.get("info", {}).get("mill_type") or MILL_HSM),
        utilities=utilities,
        info=dict(data.get("info", {})),
    )


def _trajectory_to_dict(traj) -> list[dict]:
    return [
        {"t0_s": s.t0, "t1_s": s.t1, "x0_m": s.x0, "v0_mps": s.v0, "a_mps2": s.a}
        for s in traj.segments
    ]


def result_to_dict(result: PieceResult) -> dict:
    return {
        "piece_id": result.piece_id,
        "product_id": result.product_id,
        "t_release_s": result.t_release,
        "t_end_s": result.t_end,
        "coiler_id": result.coiler_id,
        "length_kinematic_m": result.length_kinematic,
        "length_geometric_m": result.length_geometric,
        "head_segments": _trajectory_to_dict(result.head),
        "tail_segments": _trajectory_to_dict(result.tail),
        "head_virtual_segments": _trajectory_to_dict(result.head_virtual),
        "events": [
            {
                "t_s": e.t,
                "kind": e.kind,
                "equipment_id": e.equipment_id,
                "x_m": e.x,
                "detail": e.detail,
            }
            for e in result.events
        ],
        "occupancy": [
            {
                "equipment_id": o.equipment_id,
                "pass_no": o.pass_no,
                "t_in_s": o.t_in,
                "t_out_s": o.t_out,
                "piece_id": o.piece_id,
            }
            for o in result.occupancy
        ],
        "warnings": list(result.warnings),
    }


def analysis_to_dict(analysis: GapAnalysis) -> dict:
    critical = analysis.critical
    return {
        "front": analysis.front_id,
        "rear": analysis.rear_id,
        "min_gap_m": analysis.min_gap,
        "t_critical_s": critical.t if critical else None,
        "x_critical_m": critical.x if critical else None,
        "section": critical.section if critical else "",
        "equipment": critical.equipment if critical else "",
        "headway_s": analysis.headway,
        "t_first_violation_s": analysis.t_first_violation,
        "ok": analysis.ok,
    }


def report_to_dict(
    case: Case,
    results: list[PieceResult],
    analyses: list[GapAnalysis],
    deviations: tuple[MassFlowDeviation, ...] = (),
    curve: list[PacingPoint] | None = None,
    min_pacing: PacingPoint | None = None,
    mc: MonteCarloResult | None = None,
) -> dict:
    report: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "pacing_s": case.settings.pacing,
        "gap_min_m": case.settings.gap_min,
        "pieces": [result_to_dict(r) for r in results],
        "gaps": [analysis_to_dict(a) for a in analyses],
        "mass_flow_deviations": [
            {
                "product_id": d.product_id,
                "pass_no": d.pass_no,
                "equipment_id": d.equipment_id,
                "v_input_mps": d.v_input,
                "v_massflow_mps": d.v_massflow,
                "deviation_pct": d.deviation_pct,
            }
            for d in deviations
        ],
    }
    if curve is not None:
        report["pacing_curve"] = [
            {
                "pacing_s": p.pacing,
                "min_gap_m": None if p.min_gap == float("inf") else p.min_gap,
                "feasible": p.feasible,
                "t_critical_s": p.t_critical,
                "x_critical_m": p.x_critical,
                "section": p.section,
                "pair": p.pair,
            }
            for p in curve
        ]
    if min_pacing is not None:
        report["min_feasible_pacing_s"] = min_pacing.pacing
        report["min_pacing_constraint"] = min_pacing.section or min_pacing.equipment
    if mc is not None:
        report["monte_carlo"] = {
            "runs": mc.runs,
            "violations": mc.violations,
            "violation_rate": mc.violation_rate,
            "mean_min_gap_m": mc.mean,
            "p05_min_gap_m": mc.percentile(0.05),
            "errors": mc.errors,
        }
    usage = analyse_utilities(case, results)
    if usage.draws:
        report["utilities"] = {
            "water_m3": usage.water_m3,
            "power_kwh": usage.power_kwh,
            "draws": [
                {
                    "piece_id": d.piece_id,
                    "equipment_id": d.equipment_id,
                    "utility": d.utility,
                    "when": d.when,
                    "t_in_s": d.t_in,
                    "t_out_s": d.t_out,
                    "rate": d.rate,
                    "quantity": d.quantity,
                }
                for d in usage.draws
            ],
        }
    return report

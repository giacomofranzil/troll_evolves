"""Web interface of the pacing tool.

It runs equally well locally on the machine of whoever uses it (127.0.0.1, no
server, no port to open) or published on an office server.
"""

from __future__ import annotations

import io
import tempfile
from dataclasses import replace
from pathlib import Path

import streamlit as st

from hsmpace.core.analysis import analyse_sequence, mass_balance
from hsmpace.core.model import Case, harmonise_tandem_speeds
from hsmpace.core.simulate import PieceResult
from hsmpace.core.studies import (
    base_results,
    gap_vs_pacing,
    min_feasible_pacing,
    monte_carlo,
    sequence,
)
from hsmpace.core.tracking import parse_tracking
from hsmpace.core.utilities import analyse_utilities
from hsmpace.example import example_case
from hsmpace.io.excel import ValidationError, read_case, write_case, write_results
from hsmpace.viz import (
    TRACE_POINT_CHOICES,
    gantt_figure,
    gap_figure,
    monte_carlo_figure,
    pacing_curve_figure,
    space_time_figure,
    utility_rate_figure,
)

PLOT_CONFIG = {
    "displaylogo": False,
    "toImageButtonOptions": {"format": "png", "scale": 3, "filename": "hsmpace"},
}
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@st.cache_data(show_spinner=False)
def _load_from_bytes(payload: bytes, name: str):
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as handle:
        handle.write(payload)
        path = Path(handle.name)
    try:
        case = read_case(path)
    finally:
        path.unlink(missing_ok=True)
    return _prepare(case)


@st.cache_data(show_spinner=False)
def _load_example():
    return _prepare(example_case())


def _prepare(case: Case):
    harmonised, deviations = harmonise_tandem_speeds(case)
    base = base_results(harmonised)
    return harmonised, deviations, base


@st.cache_data(show_spinner=False)
def _template_bytes(with_data: bool) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as handle:
        path = Path(handle.name)
    write_case(example_case(), path, include_data=with_data)
    payload = path.read_bytes()
    path.unlink(missing_ok=True)
    return payload


def _results_bytes(case, results, analyses, deviations, curve, min_pacing, mc) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as handle:
        path = Path(handle.name)
    write_results(path, case, results, analyses, deviations, curve, min_pacing, mc)
    payload = path.read_bytes()
    path.unlink(missing_ok=True)
    return payload


def _events_csv(results: list[PieceResult]) -> str:
    buffer = io.StringIO()
    buffer.write("piece,t_s,event,equipment,x_m,detail\n")
    for res in results:
        for e in res.events:
            buffer.write(
                f"{res.piece_id},{e.t:.3f},{e.kind},{e.equipment_id},{e.x:.2f},\"{e.detail}\"\n"
            )
    return buffer.getvalue()


def main() -> None:
    st.set_page_config(page_title="HSM pacing", page_icon="~", layout="wide")
    st.title("Space-time diagram and pacing of a Hot Strip Mill")

    with st.sidebar:
        st.header("Input")
        uploaded = st.file_uploader("Input workbook (.xlsx)", type=["xlsx"])
        st.caption(
            "With no file loaded the built-in example mill is used, with invented "
            "but plausible data."
        )
        st.download_button(
            "Download the empty template",
            data=_template_bytes(False),
            file_name="hsm_template.xlsx",
            mime=XLSX_MIME,
            width="stretch",
        )
        st.download_button(
            "Download the filled example",
            data=_template_bytes(True),
            file_name="hsm_example.xlsx",
            mime=XLSX_MIME,
            width="stretch",
        )

    try:
        if uploaded is not None:
            case, deviations, base = _load_from_bytes(uploaded.getvalue(), uploaded.name)
            source = uploaded.name
        else:
            case, deviations, base = _load_example()
            source = "example mill"
    except ValidationError as exc:
        st.error("The workbook is not valid: fix the cells listed below and load it again.")
        for issue in exc.issues:
            st.write(
                f"- **{issue.sheet}!{issue.cell}** {issue.message}"
                if issue.cell
                else f"- {issue.message}"
            )
        st.stop()
    except Exception as exc:  # noqa: BLE001 - readable message instead of a traceback
        st.error(f"Error while reading the file: {exc}")
        st.stop()

    with st.sidebar:
        st.header("Scenario")
        settings = case.settings
        pacing = st.slider(
            "Pacing [s]",
            min_value=float(settings.pacing_scan_min),
            max_value=float(settings.pacing_scan_max),
            value=float(settings.pacing),
            step=1.0,
            help="Cadence at which pieces enter the process.",
        )
        gap_min = st.number_input(
            "Minimum gap required [m]", min_value=0.0, value=float(settings.gap_min), step=1.0
        )
        n_pieces = st.slider(
            "Pieces in sequence",
            min_value=2,
            max_value=8,
            value=max(2, min(8, settings.n_pieces)),
            help="The product and coiler cycles in the workbook repeat over this many pieces.",
        )
        time_down = st.checkbox("Time increasing downwards", value=settings.time_axis_down)
        show_virtual = st.checkbox(
            "Show the virtual head",
            value=False,
            help="The unconstrained head, which carries on beyond the coiler and drives "
            "the zoom rolling trigger.",
        )
        n_points = st.select_slider(
            "Material points on the diagram",
            options=TRACE_POINT_CHOICES,
            value=2,
            help="Head and tail always. Extra traces are reconstructed after the "
            "simulation, as a geometric fraction of the current length.",
        )
        st.header("Robustness")
        run_mc = st.checkbox("Run the Monte Carlo", value=False)
        mc_runs = st.number_input(
            "Runs", min_value=50, max_value=20000, value=int(settings.mc_runs), step=50
        )

    seq = settings.piece_products
    case = replace(
        case,
        settings=replace(
            settings,
            pacing=pacing,
            gap_min=gap_min,
            n_pieces=n_pieces,
            piece_products=tuple(seq[i % len(seq)] for i in range(n_pieces)) if seq else (),
            mc_runs=int(mc_runs),
            time_axis_down=time_down,
        ),
    )

    results = sequence(case, base, pacing)
    analyses = analyse_sequence(results, gap_min, case.line)
    usage = analyse_utilities(case, results)
    worst = min(analyses, key=lambda a: a.min_gap) if analyses else None

    with st.spinner("Scanning the pacing..."):
        curve = gap_vs_pacing(case, base)
        min_pacing = min_feasible_pacing(case, base, curve)

    mc = None
    if run_mc:
        with st.spinner(f"Monte Carlo over {int(mc_runs)} runs..."):
            mc = monte_carlo(case, pacing=pacing, runs=int(mc_runs))

    assignment = ", ".join(f"{r.piece_id}→{r.coiler_id or '-'}" for r in results)
    st.caption(
        f"Coiler assignment (repeating cycle from the workbook): {assignment}. "
        "Zoom rolling uses the same virtual-head trigger for every mandrel; "
        "pinning and the tail slowdown use the assigned coiler."
    )

    cols = st.columns(4)
    cols[0].metric("Minimum gap", f"{worst.min_gap:.1f} m" if worst else "no interaction")
    cols[1].metric(
        "Outcome",
        "feasible" if (worst is None or worst.ok) else "violation",
        delta=None if worst is None else f"{worst.min_gap - gap_min:+.1f} m of margin",
        delta_color="normal" if (worst is None or worst.ok) else "inverse",
    )
    cols[2].metric(
        "Minimum feasible pacing",
        f"{min_pacing.pacing:.0f} s" if min_pacing else "not found",
    )
    cols[3].metric(
        "Margin on the pacing",
        f"{pacing - min_pacing.pacing:+.0f} s" if min_pacing else "-",
    )

    if worst and worst.critical:
        where = worst.critical.section or "line"
        near = f", near {worst.critical.equipment}" if worst.critical.equipment else ""
        st.caption(
            f"Source: {source}. Critical point between {worst.front_id} and {worst.rear_id} at "
            f"x = {worst.critical.x:.1f} m ({where}{near}) at t = {worst.critical.t:.1f} s"
            + (f", that is {worst.headway:.1f} s of time distance." if worst.headway else ".")
        )

    tabs = st.tabs(
        ["Diagram", "Gap", "Pacing", "Occupancy", "Events", "Data and checks", "Measurements"]
    )

    with tabs[0]:
        st.plotly_chart(
            space_time_figure(
                case,
                results,
                analyses,
                time_down,
                show_virtual_head=show_virtual,
                n_points=int(n_points),
            ),
            width="stretch",
            config=PLOT_CONFIG,
        )
        st.caption(
            "Every piece is the band between head and tail. Extra material points, when "
            "asked for, are a geometric fraction of that length, drawn after the run; "
            "they do not enter the event loop. The band widens where the piece is being "
            "rolled and narrows once the head is gripped by the coiler. Use the camera "
            "icon to export the picture: the PNG comes out at triple resolution."
        )

    with tabs[1]:
        st.plotly_chart(gap_figure(analyses, gap_min), width="stretch", config=PLOT_CONFIG)
        st.caption(
            "Each curve is the distance, over time, between the tail of the piece in front "
            "and the head of the one behind. The dashed line is the threshold; the marker "
            "is the closest approach of that pair."
        )
        if analyses:
            st.dataframe(
                [
                    {
                        "pair": f"{a.front_id} / {a.rear_id}",
                        "minimum gap [m]": round(a.min_gap, 2),
                        "t [s]": round(a.critical.t, 1) if a.critical else None,
                        "x [m]": round(a.critical.x, 1) if a.critical else None,
                        "section": a.critical.section if a.critical else "",
                        "time gap [s]": round(a.headway, 1) if a.headway else None,
                        "outcome": "ok" if a.ok else "violation",
                    }
                    for a in analyses
                ],
                width="stretch",
                hide_index=True,
            )

    with tabs[2]:
        st.plotly_chart(
            pacing_curve_figure(curve, gap_min, pacing, min_pacing),
            width="stretch",
            config=PLOT_CONFIG,
        )
        st.caption(
            "The minimum pacing is read where the curve crosses the threshold. The "
            "vertical distance from the threshold is the margin being worked with."
        )
        if mc is not None:
            st.plotly_chart(
                monte_carlo_figure(mc, gap_min), width="stretch", config=PLOT_CONFIG
            )
            st.write(
                f"Over {mc.runs} runs with speeds within "
                f"{case.settings.mc_speed_tol_pct:g}% and dead times dispersed by "
                f"{case.settings.mc_delay_sigma:g} s: **{mc.violations} violations** "
                f"({100 * mc.violation_rate:.1f}%), mean gap {mc.mean:.1f} m, "
                f"fifth percentile {mc.percentile(0.05):.1f} m."
            )
        else:
            st.info("Enable the Monte Carlo in the sidebar for the robustness estimate.")

    with tabs[3]:
        st.plotly_chart(gantt_figure(case, results), width="stretch", config=PLOT_CONFIG)
        st.caption(
            "Busy time of every device with occupy enabled: stands (bite to tail-out, "
            "or the footprint when occupy_before_m / occupy_after_m are set), coilers, "
            "the coilbox, and markers such as descalers. A reversing bar can occupy "
            "the same device twice."
        )
        if usage.empty:
            st.info(
                "No Utilities sheet (or it is empty): occupancy is shown, consumption "
                "is not calculated. Add water / power recipes on the Utilities sheet."
            )
        else:
            cols_u = st.columns(2)
            cols_u[0].metric("Water over the sequence", f"{usage.water_m3:.2f} m³")
            cols_u[1].metric("Electrical energy over the sequence", f"{usage.power_kwh:.1f} kWh")
            st.plotly_chart(
                utility_rate_figure(usage, "water"), width="stretch", config=PLOT_CONFIG
            )
            st.plotly_chart(
                utility_rate_figure(usage, "power"), width="stretch", config=PLOT_CONFIG
            )
            st.caption(
                "Rates are piecewise constant on occupancy: water in L/s, power in kW. "
                "Overlapping pieces add. Totals are the integral over the simulated "
                "sequence, not a plant shift. rolling recipes apply only to stands."
            )
            st.dataframe(
                [
                    {
                        "piece": d.piece_id,
                        "equipment": d.equipment_id,
                        "utility": d.utility,
                        "when": d.when,
                        "from [s]": round(d.t_in, 1),
                        "to [s]": round(d.t_out, 1),
                        "rate": round(d.rate, 1),
                        "quantity": round(d.quantity, 2),
                    }
                    for d in usage.draws
                ],
                width="stretch",
                hide_index=True,
            )

    with tabs[4]:
        piece_ids = [r.piece_id for r in results]
        selected = st.selectbox("Piece", piece_ids)
        chosen = next(r for r in results if r.piece_id == selected)
        st.caption(
            f"Assigned coiler: {chosen.coiler_id or 'none'} "
            f"(pin at {chosen.x_coiler:.1f} m)."
            if chosen.x_coiler is not None
            else "No coiler in the layout."
        )
        st.dataframe(
            [
                {
                    "t [s]": round(e.t, 2),
                    "event": e.kind,
                    "equipment": e.equipment_id,
                    "x [m]": round(e.x, 1),
                    "detail": e.detail,
                }
                for e in chosen.events
            ],
            width="stretch",
            hide_index=True,
            height=460,
        )
        st.download_button(
            "Download the events as CSV",
            data=_events_csv(results),
            file_name="events.csv",
            mime="text/csv",
        )

    with tabs[5]:
        st.subheader("Piece assignment")
        st.dataframe(
            [
                {
                    "piece": r.piece_id,
                    "product": r.product_id,
                    "coiler": r.coiler_id or "-",
                    "x coiler [m]": round(r.x_coiler, 1) if r.x_coiler is not None else None,
                }
                for r in results
            ],
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "The zoom trigger is the virtual travel past the last stand, the TRoll "
            "convention: it does not change with the assigned coiler. Pinning and "
            "the tail slowdown do. Reversing clearance is the stop position; v* is "
            "the tail-out speed the model derived to hit it."
        )

        st.subheader("Mass balance")
        st.dataframe(
            [
                {
                    "product": c.piece_id,
                    "kinematic length [m]": round(c.length_kinematic, 2),
                    "geometric length [m]": round(c.length_geometric, 2),
                    "deviation [%]": round(c.error_pct, 4),
                    "outcome": "ok" if c.ok else "warning",
                }
                for c in mass_balance(results)
            ],
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "The two lengths coincide by construction: a deviation signals an error in "
            "the input or in the model."
        )

        st.subheader("Tandem speeds recomputed from the master stand")
        if deviations:
            st.dataframe(
                [
                    {
                        "product": d.product_id,
                        "pass": d.pass_no,
                        "stand": d.equipment_id,
                        "v entered [m/s]": round(d.v_input, 3),
                        "v from balance [m/s]": round(d.v_massflow, 3),
                        "deviation [%]": round(d.deviation_pct, 2),
                    }
                    for d in deviations
                ],
                width="stretch",
                hide_index=True,
            )
            st.caption(
                "In a tandem mill the strip between two stands has a fixed length, so the "
                "mass flow balance is a physical constraint and not a check: speeds are "
                "recomputed from the master and this is how far they sit from the ones "
                "entered."
            )
        else:
            st.success("The tandem speeds entered are already consistent with the mass balance.")

        for remark in case.warnings:
            st.warning(remark)
        for res in results[:1]:
            for warning in res.warnings:
                st.warning(warning)

        st.subheader("Export")
        st.download_button(
            "Download the results as Excel",
            data=_results_bytes(case, results, analyses, deviations, curve, min_pacing, mc),
            file_name="hsmpace_results.xlsx",
            mime=XLSX_MIME,
        )

    with tabs[6]:
        st.subheader("Comparison against measured tracking")
        st.write(
            "CSV format: `piece_id,time_s,head_m,tail_m` with `tail_m` optional and "
            "positions referred to the same origin as the layout."
        )
        measured = st.file_uploader("Measured tracking (.csv)", type=["csv"], key="tracking")
        if measured is not None:
            try:
                series = parse_tracking(measured.getvalue().decode("utf-8-sig").splitlines())
            except ValueError as exc:
                st.error(str(exc))
            else:
                offset = st.number_input(
                    "Time shift applied to the measurements [s]", value=0.0, step=1.0
                )
                shifted = [s.shift(offset) for s in series]
                st.plotly_chart(
                    space_time_figure(
                        case,
                        results,
                        analyses,
                        time_down,
                        tracking=shifted,
                        n_points=int(n_points),
                    ),
                    width="stretch",
                    config=PLOT_CONFIG,
                )
        else:
            st.info(
                "No file loaded. Overlaying simulated against measured is the quickest way "
                "to get the numbers coming out of this tool accepted on the shop floor."
            )


if __name__ == "__main__":
    main()

"""Command line interface.

Beyond interactive use, the ``to-json`` and ``run`` commands are the hook for a
Level 2 system written in another language: a case goes in as JSON and a report
comes out as JSON, with no dependency on Excel.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core.analysis import analyse_sequence
from .core.contract import case_from_dict, case_to_dict, report_to_dict
from .core.model import harmonise_tandem_speeds
from .core.studies import base_results, gap_vs_pacing, min_feasible_pacing, monte_carlo, sequence
from .example import example_case
from .io.excel import ValidationError, read_case, write_case, write_results

DEFAULT_PORT = 8731

_XML_NOT_A_RUN = (
    "TRoll XML is not a simulation input. Map it onto a workbook first:\n"
    "  hsmpace import dump.xml case.xlsx"
)


def _load(path: str | None) -> "object":
    if path is None:
        return example_case()
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".xml":
        raise ValueError(_XML_NOT_A_RUN)
    if suffix == ".json":
        return case_from_dict(json.loads(p.read_text(encoding="utf-8")))
    return read_case(p)


def _cmd_import(args: argparse.Namespace) -> int:
    from .io.troll_xml import write_troll_case

    xml = Path(args.input)
    if xml.suffix.lower() != ".xml":
        raise ValueError("import expects a TRoll ProcessData .xml dump")
    case = write_troll_case(xml, args.output)
    for remark in case.warnings:
        print(f"Warning: {remark}")
    print(f"Written the mapped workbook: {args.output}")
    return 0


def _cmd_template(args: argparse.Namespace) -> int:
    path = write_case(example_case(), args.output, include_data=args.with_example)
    kind = "filled example" if args.with_example else "empty template"
    print(f"Written the {kind}: {path}")
    return 0


def _cmd_to_json(args: argparse.Namespace) -> int:
    case = _load(args.input)
    payload = json.dumps(case_to_dict(case), indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
        print(f"Written {args.output}")
    else:
        print(payload)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    case = _load(args.input)
    case, deviations = harmonise_tandem_speeds(case)
    if args.pacing is not None:
        from dataclasses import replace

        case = replace(case, settings=replace(case.settings, pacing=args.pacing))

    base = base_results(case)
    results = sequence(case, base, case.settings.pacing)
    analyses = analyse_sequence(results, case.settings.gap_min, case.line)

    curve = gap_vs_pacing(case, base) if args.scan else None
    best = min_feasible_pacing(case, base, curve) if args.scan else None
    mc = monte_carlo(case, runs=args.monte_carlo) if args.monte_carlo else None

    if args.json:
        report = report_to_dict(case, results, analyses, deviations, curve, best, mc)
        Path(args.json).write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"JSON report written to {args.json}")

    if args.excel:
        write_results(args.excel, case, results, analyses, deviations, curve, best, mc)
        print(f"Excel results written to {args.excel}")

    for remark in case.warnings:
        print(f"Warning: {remark}")
    for warning in dict.fromkeys(w for r in results for w in r.warnings):
        print(f"Warning: {warning}")

    print(f"Simulated pacing: {case.settings.pacing:.1f} s over {len(results)} pieces")
    if analyses:
        worst = min(analyses, key=lambda a: a.min_gap)
        state = "feasible" if worst.ok else "VIOLATION"
        where = worst.critical
        print(
            f"Minimum gap {worst.min_gap:.1f} m between {worst.front_id} and "
            f"{worst.rear_id} ({state})"
        )
        if where:
            print(
                f"  critical point at x={where.x:.1f} m, t={where.t:.1f} s"
                + (f", section {where.section}" if where.section else "")
                + (f", time gap {worst.headway:.1f} s" if worst.headway else "")
            )
    else:
        print("The pieces are never on the line at the same time.")

    if best is not None:
        print(
            f"Minimum feasible pacing: {best.pacing:.1f} s"
            + (f" (constraint in {best.section})" if best.section else "")
        )
    if mc is not None:
        print(
            f"Monte Carlo over {mc.runs} runs: {mc.violations} violations "
            f"({100 * mc.violation_rate:.1f}%), mean gap {mc.mean:.1f} m, "
            f"fifth percentile {mc.percentile(0.05):.1f} m"
        )

    if analyses and not min(analyses, key=lambda a: a.min_gap).ok:
        return 2
    return 0


def _cmd_app(args: argparse.Namespace) -> int:
    from streamlit.web import cli as stcli

    script = Path(__file__).parent / "app" / "streamlit_app.py"
    sys.argv = [
        "streamlit",
        "run",
        str(script),
        "--server.port",
        str(args.port),
        "--server.address",
        args.address,
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
    return int(stcli.main() or 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hsmpace",
        description="Space-time diagram and pacing analysis for a Hot Strip Mill",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("template", help="generate the input workbook")
    p.add_argument("output", help="path of the .xlsx file to create")
    p.add_argument(
        "--with-example",
        action="store_true",
        help="fill the workbook with the example mill",
    )
    p.set_defaults(func=_cmd_template)

    p = sub.add_parser(
        "import",
        help="map a TRoll ProcessData dump onto an input workbook",
    )
    p.add_argument("input", help="TRoll ProcessData .xml")
    p.add_argument("output", help="path of the .xlsx workbook to write")
    p.set_defaults(func=_cmd_import)

    p = sub.add_parser("to-json", help="convert an input into JSON for the Level 2 system")
    p.add_argument("input", nargs="?", help=".xlsx or .json file (empty = built-in example)")
    p.add_argument("-o", "--output", help="JSON file to write")
    p.set_defaults(func=_cmd_to_json)

    p = sub.add_parser("run", help="simulate and analyse the gap")
    p.add_argument("input", nargs="?", help=".xlsx or .json file (empty = built-in example)")
    p.add_argument("--pacing", type=float, help="override the pacing from the file")
    p.add_argument("--scan", action="store_true", help="compute the gap versus pacing curve")
    p.add_argument(
        "--monte-carlo", type=int, metavar="N", help="run N robustness draws"
    )
    p.add_argument("--json", help="write the report as JSON")
    p.add_argument("--excel", help="write the results as xlsx")
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("app", help="start the web interface")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--address", default="127.0.0.1")
    p.set_defaults(func=_cmd_app)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

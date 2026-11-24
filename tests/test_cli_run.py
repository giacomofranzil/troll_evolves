"""``hsmpace run`` on the coiler cycle: the default, its note, and a wrong pattern."""

from __future__ import annotations

import json
from dataclasses import replace

from openpyxl import load_workbook

from hsmpace.cli import main
from hsmpace.core.contract import case_to_dict
from hsmpace.example import example_case
from hsmpace.io.excel import write_case

NOTE = (
    "Note: coiler_pattern is empty: all coilers are used in turn, in Layout order "
    "(DC1, DC2, DC3)."
)


def _workbook(tmp_path, pattern: str):
    path = write_case(example_case(), tmp_path / "case.xlsx")
    wb = load_workbook(path)
    ws = wb["Simulation"]
    for row in range(2, ws.max_row + 1):
        if ws.cell(row=row, column=1).value == "coiler_pattern":
            ws.cell(row=row, column=2).value = pattern
    wb.save(path)
    return path


def test_run_with_an_empty_pattern_uses_all_coilers_and_says_so(tmp_path, capsys):
    report_path = tmp_path / "report.json"
    code = main(["run", str(_workbook(tmp_path, "")), "--json", str(report_path)])
    out = capsys.readouterr().out

    assert code == 0
    assert NOTE in out.splitlines()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert [p["coiler_id"] for p in report["pieces"]] == ["DC1", "DC2", "DC3"]


def test_run_with_a_pattern_prints_no_note(tmp_path, capsys):
    assert main(["run", str(_workbook(tmp_path, "DC2,DC1"))]) == 0
    assert "Note:" not in capsys.readouterr().out


def test_run_from_json_takes_the_same_default(tmp_path, capsys):
    original = example_case()
    case = replace(original, settings=replace(original.settings, coiler_pattern=()))
    source = tmp_path / "case.json"
    source.write_text(json.dumps(case_to_dict(case)), encoding="utf-8")
    report_path = tmp_path / "report.json"

    assert main(["run", str(source), "--json", str(report_path)]) == 0
    assert NOTE in capsys.readouterr().out.splitlines()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert [p["coiler_id"] for p in report["pieces"]] == ["DC1", "DC2", "DC3"]


def test_run_still_rejects_a_wrong_pattern(tmp_path, capsys):
    assert main(["run", str(_workbook(tmp_path, "DC1,DC9"))]) == 1
    err = capsys.readouterr().err
    assert "Simulation!" in err
    assert "'DC9' is not a coiler in the layout" in err

"""Checks that the web application starts and renders without exceptions.

`streamlit run` executes the file as a standalone script, with no package
context: in that mode a relative import fails with "attempted relative import
with no known parent package", and the error **is not visible by probing the
port**, because the server still answers 200 and the message only shows up in
the browser. These tests reproduce that very same start-up mode.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import hsmpace

SCRIPT = Path(hsmpace.__file__).parent / "app" / "streamlit_app.py"


@pytest.fixture(scope="module")
def app() -> AppTest:
    at = AppTest.from_file(str(SCRIPT), default_timeout=180)
    at.run()
    return at


def test_the_app_starts_without_exceptions(app: AppTest):
    assert not app.exception, [e.value for e in app.exception]


def test_the_summary_metrics_are_present(app: AppTest):
    labels = {m.label for m in app.metric}
    assert {
        "Minimum gap",
        "Outcome",
        "Minimum feasible pacing",
        "Margin on the pacing",
        "Water over the sequence",
        "Electrical energy over the sequence",
    } <= labels


def test_the_main_charts_are_drawn(app: AppTest):
    # space-time, gap, pacing, Gantt, water rate, power rate
    assert len(app.get("plotly_chart")) >= 6


def test_a_tight_pacing_produces_a_violation():
    at = AppTest.from_file(str(SCRIPT), default_timeout=180)
    at.run()
    at.sidebar.slider[0].set_value(75.0).run()
    assert not at.exception, [e.value for e in at.exception]
    outcome = next(m for m in at.metric if m.label == "Outcome")
    assert outcome.value == "violation"


def _piece_table(at: AppTest):
    """The "Piece assignment" table of the Data and checks tab."""
    return next(
        d.value for d in at.dataframe if {"piece", "product", "coiler"} <= set(d.value.columns)
    )


def test_the_product_selector_defaults_to_the_workbook_sequence(app: AppTest):
    selector = app.sidebar.selectbox[0]
    assert selector.label == "Product"
    assert selector.options[0] == "Workbook sequence"
    assert [o.split(" — ")[0] for o in selector.options[1:]] == ["P1", "P2"]
    assert selector.value is None
    # piece_products of the example workbook is P1,P2,P1
    assert list(_piece_table(app)["product"]) == ["P1", "P2", "P1"]


def test_choosing_a_product_runs_every_piece_with_it():
    at = AppTest.from_file(str(SCRIPT), default_timeout=180)
    at.run()
    before = next(m for m in at.metric if m.label == "Minimum feasible pacing").value

    at.sidebar.selectbox[0].select("P2").run()
    assert not at.exception, [e.value for e in at.exception]
    table = _piece_table(at)
    assert list(table["product"]) == ["P2", "P2", "P2"]
    assert list(table["coiler"]) == ["DC1", "DC2", "DC3"]
    after = next(m for m in at.metric if m.label == "Minimum feasible pacing").value
    assert after != before, "the studies must follow the chosen product"

    pieces = next(s for s in at.sidebar.slider if s.label == "Pieces in sequence")
    pieces.set_value(5).run()
    assert list(_piece_table(at)["product"]) == ["P2"] * 5

    at.sidebar.selectbox[0].select(None).run()
    assert list(_piece_table(at)["product"]) == ["P1", "P2", "P1", "P1", "P2"]


def test_the_scenario_products_follow_the_workbook_unless_one_is_chosen():
    from hsmpace.app.streamlit_app import _piece_products

    assert _piece_products(("P1", "P2", "P1"), 5, None) == ("P1", "P2", "P1", "P1", "P2")
    assert _piece_products(("P1", "P2", "P1"), 2, None) == ("P1", "P2")
    # an empty piece_products cell stays empty: the model repeats the first product
    assert _piece_products((), 4, None) == ()
    assert _piece_products(("P1", "P2", "P1"), 4, "P2") == ("P2",) * 4
    assert _piece_products((), 3, "P7") == ("P7",) * 3


def _example_workbook_without_coiler_pattern(tmp_path) -> bytes:
    from dataclasses import replace

    from hsmpace.example import example_case
    from hsmpace.io.excel import write_case

    case = example_case()
    case = replace(case, settings=replace(case.settings, coiler_pattern=()))
    return write_case(case, tmp_path / "no_pattern.xlsx").read_bytes()


def test_a_workbook_without_a_coiler_pattern_loads_with_every_coiler(tmp_path):
    from hsmpace.app.streamlit_app import _load_from_bytes

    payload = _example_workbook_without_coiler_pattern(tmp_path)
    case, _deviations, base = _load_from_bytes(payload, "no_pattern.xlsx")
    assert case.settings.coiler_pattern == ()
    assert {coiler for _product, coiler in base} == {"DC1", "DC2", "DC3"}
    assert {product for product, _coiler in base} == {"P1", "P2"}


def test_the_app_notes_the_default_coiler_cycle(app: AppTest, tmp_path):
    def assignment(at: AppTest) -> str:
        return next(c.value for c in at.caption if c.value.startswith("Coiler assignment"))

    assert "repeating cycle from the workbook" in assignment(app)
    assert "coiler_pattern is empty" not in assignment(app)

    at = AppTest.from_file(str(SCRIPT), default_timeout=180)
    at.run()
    uploader = at.sidebar.get("file_uploader")
    if not uploader or not hasattr(uploader[0], "set_value"):
        pytest.skip("this Streamlit cannot upload a file in AppTest")
    payload = _example_workbook_without_coiler_pattern(tmp_path)
    uploader[0].set_value(("no_pattern.xlsx", payload, "application/octet-stream")).run()

    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]
    caption = assignment(at)
    assert "Coiler assignment (default cycle): #1→DC1, #2→DC2, #3→DC3." in caption
    assert (
        "coiler_pattern is empty: all coilers are used in turn, in Layout order "
        "(DC1, DC2, DC3)." in caption
    )
    assert list(_piece_table(at)["coiler"]) == ["DC1", "DC2", "DC3"]


def test_xml_is_mapped_to_a_workbook_without_simulating():
    from hsmpace.app.streamlit_app import _workbook_from_xml_bytes

    xml = Path(__file__).parent / "data" / "troll_cbx.xml"
    payload, summary = _workbook_from_xml_bytes(xml.read_bytes(), "troll_cbx.xml")
    assert payload[:2] == b"PK"
    assert summary["n_products"] == 1
    assert any(row["id"] == "CBX" and row["kind"] == "coilbox" for row in summary["equipment"])
    assert any("troll_cbx.xml" in w for w in summary["warnings"])

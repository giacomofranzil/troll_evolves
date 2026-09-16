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

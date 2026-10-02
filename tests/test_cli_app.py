"""``hsmpace app`` stays on 127.0.0.1:8731 and points at the Streamlit script."""

from __future__ import annotations

from pathlib import Path

from hsmpace.cli import DEFAULT_PORT, _streamlit_argv


def test_app_argv_matches_hsmpace_app_defaults():
    argv = _streamlit_argv(DEFAULT_PORT, "127.0.0.1")
    script = Path(argv[2])
    assert argv[:2] == ["streamlit", "run"]
    assert script.name == "streamlit_app.py"
    assert script.is_file()
    flags = dict(zip(argv[3::2], argv[4::2], strict=True))
    assert flags["--server.port"] == "8731"
    assert flags["--server.address"] == "127.0.0.1"
    assert flags["--server.headless"] == "true"
    assert flags["--browser.gatherUsageStats"] == "false"
    assert "--server.fileWatcherType" not in argv

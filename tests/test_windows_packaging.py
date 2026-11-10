"""Static checks for the manually dispatched Windows distribution.

The executable itself is built and started on ``windows-latest``. These checks
run on every development platform and keep the spec, workflow, and colleague
instructions wired together.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "hsmpace.spec"
ENTRYPOINT = ROOT / "packaging" / "hsmpace_windows.py"
STREAMLIT_HOOK = ROOT / "packaging" / "hooks" / "hook-streamlit.py"
WINDOWS_README = ROOT / "packaging" / "WINDOWS-README.txt"
WORKFLOW = ROOT / ".github" / "workflows" / "windows-app.yml"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_pyinstaller_sources_are_valid_python():
    for path in (SPEC, ENTRYPOINT, STREAMLIT_HOOK):
        ast.parse(_text(path), filename=str(path))


def test_spec_uses_spec_relative_paths_and_ships_runtime_data():
    spec = _text(SPEC)

    assert 'os.path.join(SPECPATH, "hsmpace_windows.py")' in spec
    assert 'pathex=[_root("src")]' in spec
    assert 'hookspath=[os.path.join(SPECPATH, "hooks")]' in spec
    assert '_root("src", "hsmpace", "app", "streamlit_app.py")' in spec
    assert '_root(".streamlit", "config.toml")' in spec
    assert '_root("packaging", "WINDOWS-README.txt")' in spec
    assert 'contents_directory="."' in spec


def test_streamlit_hook_collects_assets_metadata_and_lazy_imports():
    hook = _text(STREAMLIT_HOOK)

    assert 'collect_all(' in hook
    assert '"streamlit"' in hook
    assert 'copy_metadata("streamlit", recursive=True)' in hook
    assert "streamlit.runtime.scriptrunner.magic_funcs" in hook


def test_workflow_builds_smokes_and_uploads_the_complete_folder():
    workflow = _text(WORKFLOW)

    assert "workflow_dispatch:" in workflow
    assert "runs-on: windows-latest" in workflow
    assert "python -m PyInstaller packaging/hsmpace.spec" in workflow
    assert "dist/hsmpace/python312.dll" in workflow
    assert "dist/hsmpace/streamlit/static/index.html" in workflow
    assert "streamlit-*.dist-info" in workflow
    assert "dist/hsmpace/.streamlit/config.toml" in workflow
    assert "dist/hsmpace/WINDOWS-README.txt" in workflow
    assert "/_stcore/health" in workflow
    assert "name: hsmpace-windows" in workflow
    assert "path: dist/hsmpace" in workflow
    assert "include-hidden-files: true" in workflow


def test_windows_readme_explains_the_portable_folder_launch():
    instructions = _text(WINDOWS_README)

    assert "Extract the entire hsmpace-windows ZIP" in instructions
    assert "do not copy hsmpace.exe" in instructions
    assert "http://127.0.0.1:8731" in instructions
    assert "No Python installation" in instructions
    assert "Close the console window" in instructions

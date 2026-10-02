# -*- mode: python ; coding: utf-8 -*-
"""Freeze ``hsmpace app`` as an onedir Windows program.

Entry is packaging/hsmpace_windows.py, which calls hsmpace.cli.main(["app"])
(127.0.0.1, port 8731). Run this spec on windows-latest. A macOS PyInstaller
folder is not hsmpace.exe.

Streamlit has no upstream PyInstaller hook; packaging/hooks/hook-streamlit.py
is that hook (static files and dist-info). plotly, altair, pyarrow, pandas,
numpy, PIL, and openpyxl are collected by the hooks in pyinstaller-hooks-contrib
once they are hidden-imported. The app source is data, not just bytecode:
Streamlit's script runner opens the .py file.
"""

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

datas = [
    ("src/hsmpace/app/streamlit_app.py", "hsmpace/app"),
    # Theme. Port, address, and headless are also flags in cli._streamlit_argv.
    # contents_directory="." puts this next to hsmpace.exe, which is the
    # working directory of a double-click. The second copy is the script-level
    # config Streamlit reads beside streamlit_app.py.
    (".streamlit/config.toml", ".streamlit"),
    (".streamlit/config.toml", "hsmpace/app/.streamlit"),
]
binaries = []
hiddenimports = [
    "hsmpace.app.streamlit_app",
    "streamlit.web.cli",
    "streamlit.runtime.scriptrunner.magic_funcs",
    # Lazy imports. Listing them runs the upstream hooks (binaries and data).
    "altair",
    "pandas",
    "numpy",
    "pyarrow",
    "plotly",
    "PIL",
    "openpyxl",
    "watchdog",
]

hiddenimports += collect_submodules("hsmpace")

# Not required by Streamlit itself (plotly is an extra; openpyxl is ours).
for package in ("plotly", "openpyxl"):
    datas += copy_metadata(package)


a = Analysis(
    ["packaging/hsmpace_windows.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=["packaging/hooks"],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="hsmpace",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    # PyInstaller 6 defaults to an _internal/ folder. "." keeps libraries beside
    # the exe, so a double-click's working directory sees .streamlit/config.toml.
    contents_directory=".",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="hsmpace",
)

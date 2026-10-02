# PyInstaller hook for Streamlit.
# pyinstaller-hooks-contrib (2026.8) ships hooks for plotly, altair, pyarrow,
# pandas, numpy, PIL, and openpyxl. It does not ship hook-streamlit.py.
# The 1.64 wheel does not either. Two things break without this hook:
# importlib.metadata.version("streamlit") needs the dist-info, and
# streamlit.file_util.get_static_dir() reads streamlit/static beside the
# package (sys._MEIPASS/streamlit/static).

from PyInstaller.utils.hooks import collect_all, copy_metadata

datas, binaries, hiddenimports = collect_all(
    "streamlit",
    filter_submodules=lambda name: not name.startswith("streamlit.testing"),
)
datas += copy_metadata("streamlit", recursive=True)

# The script runner imports this by name.
hiddenimports += ["streamlit.runtime.scriptrunner.magic_funcs"]

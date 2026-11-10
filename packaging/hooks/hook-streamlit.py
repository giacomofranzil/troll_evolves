# PyInstaller hook for Streamlit.
# PyInstaller's hook collection covers plotly, altair, pyarrow, pandas, numpy,
# PIL, and openpyxl, but neither it nor Streamlit ships hook-streamlit.py.
# Two things break without this hook:
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

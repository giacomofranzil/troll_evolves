"""Double-click entry for the Windows build.

Same call as the ``hsmpace app`` console script: ``main(["app"])`` in
``src/hsmpace/cli.py``, which serves the Streamlit app on 127.0.0.1 port 8731.
Extra arguments after the program name are forwarded (``hsmpace.exe --port 9000``).
"""

from __future__ import annotations

import sys

from hsmpace.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["app", *sys.argv[1:]]))

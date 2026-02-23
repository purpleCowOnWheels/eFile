"""Launch the pFile Streamlit UI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    app_path = Path(__file__).parent / "app.py"
    sys.exit(subprocess.call(["streamlit", "run", str(app_path)] + sys.argv[1:]))

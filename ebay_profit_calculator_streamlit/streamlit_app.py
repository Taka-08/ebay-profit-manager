"""Compatibility launcher for the restored latest profit calculator."""

from pathlib import Path
import runpy


LATEST_APP = Path(__file__).resolve().parent.parent / "streamlit_app.py"

if not LATEST_APP.exists():
    raise FileNotFoundError(f"Latest profit calculator was not found: {LATEST_APP}")

runpy.run_path(str(LATEST_APP), run_name="__main__")

#!/usr/bin/env python3
"""Convenience launcher — `python run.py` from the project root.

Equivalent to `python -m mhfu_hud`. Use the project's own venv:
    .venv/bin/python run.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mhfu_hud.cli import main  # noqa: E402

if __name__ == "__main__":
    main()

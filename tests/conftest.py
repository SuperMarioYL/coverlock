"""Test bootstrap: make ``coverlock`` importable straight from a clone.

The package uses a ``src/`` layout. When the project is *not* installed (a fresh
clone, or a CI job that skips ``pip install -e .``), nothing would otherwise put
``src/`` on ``sys.path`` and every ``import coverlock`` in the suite would fail
with ``ModuleNotFoundError``. Prepending ``src/`` here — in addition to the
``pythonpath = ["src"]`` entry in ``pyproject.toml`` — guarantees the suite
collects and runs regardless of how the runner was invoked.

If the package *is* installed, this is a harmless no-op (the src path simply
shadows nothing new).
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir():
    src_str = str(_SRC)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)

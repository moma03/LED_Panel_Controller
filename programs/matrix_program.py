"""Import bootstrap for hzeller's own SampleBase, plus small drawing helpers shared
by the idle/transition/shutdown display programs.

Subclass SampleBase (re-exported here) directly for a new display program -- every
--led-* hardware flag is parsed for free, no wrapper class of ours needed. The
controller assembles those flags from its own config.yaml `matrix:` block and
substitutes them into any command via the {matrix_options} placeholder (see
AppConfig.render_command / MatrixConfig in led_controller/config.py), so this works
the same way whether the target program is one of ours or a third-party
rpi-rgb-led-matrix-based binary.
"""

from __future__ import annotations

import os
import sys

_SUBMODULE_ROOT = os.path.join(os.path.dirname(__file__), "..", "third_party", "rpi-rgb-led-matrix")
_SAMPLES_DIR = os.path.join(_SUBMODULE_ROOT, "bindings", "python", "samples")
FONTS_DIR = os.path.join(_SUBMODULE_ROOT, "fonts")

sys.path.insert(0, os.path.abspath(_SAMPLES_DIR))

try:
    from samplebase import SampleBase  # noqa: F401 (re-exported for callers)
except ImportError as exc:
    raise ImportError(
        "Could not import hzeller's SampleBase from the rpi-rgb-led-matrix submodule "
        f"(looked in {_SAMPLES_DIR}). Make sure the submodule is checked out "
        "(`git submodule update --init`) -- see README.md."
    ) from exc

try:
    from rgbmatrix import graphics  # noqa: F401 (re-exported for callers)
except ImportError as exc:
    raise ImportError(
        "rgbmatrix is not installed in this Python interpreter "
        f"({os.path.realpath(sys.executable)}). Build it with "
        "`pip install .` from third_party/rpi-rgb-led-matrix, using the same "
        "venv/interpreter you're running this script with -- see README.md. "
        "If you're running under sudo, make sure sudo is invoking that venv's "
        "python (e.g. `sudo <venv>/bin/python3 ...`), not the system one."
    ) from exc


def load_font(name: str) -> "graphics.Font":
    font = graphics.Font()
    font.LoadFont(os.path.join(FONTS_DIR, name))
    return font


def text_width(font: "graphics.Font", text: str) -> int:
    """Sums each glyph's width -- the Python bindings only expose per-character
    widths, not a whole-string measurement, so this is needed to center text."""
    return sum(font.CharacterWidth(ord(ch)) for ch in text)

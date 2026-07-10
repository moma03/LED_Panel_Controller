"""Shared RGBMatrix setup for the idle/transition/shutdown display programs.

Building the rgbmatrix Python extension (from the third_party/rpi-rgb-led-matrix
submodule) is a one-time step on the Raspberry Pi itself -- see the top-level
README.md. This module only locates and imports the compiled extension; it
doesn't build it. If it isn't installed system-wide (`make install-python`),
it falls back to importing straight from the submodule's build directory.
"""

from __future__ import annotations

import argparse
import os
import sys

_SUBMODULE_ROOT = os.path.join(os.path.dirname(__file__), "..", "third_party", "rpi-rgb-led-matrix")
_SUBMODULE_BINDINGS = os.path.join(_SUBMODULE_ROOT, "bindings", "python")
FONTS_DIR = os.path.join(_SUBMODULE_ROOT, "fonts")

try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics
except ImportError:
    sys.path.append(os.path.abspath(_SUBMODULE_BINDINGS))
    from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics  # noqa: F401 (re-exported for callers)


def add_matrix_arguments(parser: argparse.ArgumentParser) -> None:
    """Adds the subset of rpi-rgb-led-matrix's standard --led-* flags that
    matter for this project's fixed single-panel-chain setup. Defaults match
    an Adafruit Triple LED Matrix Bonnet driving one 64x32 chain."""
    parser.add_argument("--led-rows", type=int, default=32, help="Panel rows (default: 32)")
    parser.add_argument("--led-cols", type=int, default=64, help="Panel columns (default: 64)")
    parser.add_argument("--led-chain", type=int, default=1, help="Daisy-chained panels (default: 1)")
    parser.add_argument("--led-parallel", type=int, default=1, help="Parallel chains, 1-3 (default: 1)")
    parser.add_argument(
        "--led-gpio-mapping",
        default="adafruit-hat-pwm",
        choices=["regular", "adafruit-hat", "adafruit-hat-pwm"],
        help="Hardware wiring (default: adafruit-hat-pwm)",
    )
    parser.add_argument("--led-slowdown-gpio", type=int, default=2, help="GPIO slowdown factor (default: 2)")
    parser.add_argument("--led-brightness", type=int, default=80, help="Brightness percent, 1-100 (default: 80)")
    parser.add_argument("--led-pwm-bits", type=int, default=11, help="PWM bits, 1-11 (default: 11)")


def build_matrix(args: argparse.Namespace) -> "RGBMatrix":
    options = RGBMatrixOptions()
    options.rows = args.led_rows
    options.cols = args.led_cols
    options.chain_length = args.led_chain
    options.parallel = args.led_parallel
    options.hardware_mapping = args.led_gpio_mapping
    options.gpio_slowdown = args.led_slowdown_gpio
    options.brightness = args.led_brightness
    options.pwm_bits = args.led_pwm_bits
    return RGBMatrix(options=options)


def load_font(name: str) -> "graphics.Font":
    font = graphics.Font()
    font.LoadFont(os.path.join(FONTS_DIR, name))
    return font


def text_width(font: "graphics.Font", text: str) -> int:
    """Sums each glyph's width -- the Python bindings only expose per-character
    widths, not a whole-string measurement, so this is needed to center text."""
    return sum(font.CharacterWidth(ord(ch)) for ch in text)

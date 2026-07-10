#!/usr/bin/env python3
"""Transition animation: shows the name of the program being switched to, then exits.

Run to completion (blocking) by TransitionManager.switch() between stopping
the old program and starting the new one -- it must exit on its own rather
than loop forever, unlike idle.py.
"""

from __future__ import annotations

import argparse
import time

from matrix_options import add_matrix_arguments, build_matrix, graphics, load_font, text_width


def main() -> None:
    parser = argparse.ArgumentParser(description="LED matrix program-switch transition")
    add_matrix_arguments(parser)
    parser.add_argument("--program-name", default="", help="Display name of the program being switched to")
    parser.add_argument("--duration", type=float, default=1.5, help="Seconds to show the message (default: 1.5)")
    args = parser.parse_args()

    matrix = build_matrix(args)
    font = load_font("7x13.bdf")
    canvas = matrix.CreateFrameCanvas()
    canvas.Fill(0, 0, 0)

    text = args.program_name or "..."
    white = graphics.Color(255, 255, 255)
    x = max(0, (canvas.width - text_width(font, text)) // 2)
    y = (canvas.height + font.height) // 2
    graphics.DrawText(canvas, font, x, y, white, text)
    matrix.SwapOnVSync(canvas)

    time.sleep(args.duration)
    matrix.Clear()


if __name__ == "__main__":
    main()

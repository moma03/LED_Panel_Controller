#!/usr/bin/env python3
"""Shutdown animation: shows a goodbye message, then exits.

Run to completion (blocking) by TransitionManager.shutdown() before the
active process is stopped and the display PSU relay is switched off.
"""

from __future__ import annotations

import argparse
import time

from matrix_options import add_matrix_arguments, build_matrix, graphics, load_font, text_width


def main() -> None:
    parser = argparse.ArgumentParser(description="LED matrix shutdown animation")
    add_matrix_arguments(parser)
    parser.add_argument("--message", default="Goodbye!", help="Message shown before the display powers off")
    parser.add_argument("--duration", type=float, default=2.0, help="Seconds to show the message (default: 2.0)")
    args = parser.parse_args()

    matrix = build_matrix(args)
    font = load_font("7x13.bdf")
    canvas = matrix.CreateFrameCanvas()
    canvas.Fill(0, 0, 0)

    white = graphics.Color(255, 255, 255)
    x = max(0, (canvas.width - text_width(font, args.message)) // 2)
    y = (canvas.height + font.height) // 2
    graphics.DrawText(canvas, font, x, y, white, args.message)
    matrix.SwapOnVSync(canvas)

    time.sleep(args.duration)
    matrix.Clear()


if __name__ == "__main__":
    main()

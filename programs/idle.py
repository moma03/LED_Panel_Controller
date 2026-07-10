#!/usr/bin/env python3
"""Idle animation: a retro test-pattern style screen with a live clock.

Runs continuously while the controller is IDLE (or ERROR, since the
controller falls back to idle on failure). The controller stops it with
SIGTERM whenever a real program starts or the display shuts down, so the
render loop must exit promptly on that signal rather than run forever.
"""

from __future__ import annotations

import argparse
import signal
import time

from matrix_options import add_matrix_arguments, build_matrix, graphics, load_font, text_width

_stop = False


def _handle_sigterm(_signum, _frame) -> None:
    global _stop
    _stop = True


def draw_frame(canvas, label_font, clock_font, label: str) -> None:
    width, height = canvas.width, canvas.height

    background = graphics.Color(30, 30, 30)
    grid_line = graphics.Color(60, 60, 60)
    white = graphics.Color(255, 255, 255)

    canvas.Fill(background.red, background.green, background.blue)

    grid_step = max(4, width // 12)
    for x in range(0, width, grid_step):
        graphics.DrawLine(canvas, x, 0, x, height - 1, grid_line)
    for y in range(0, height, grid_step):
        graphics.DrawLine(canvas, 0, y, width - 1, y, grid_line)

    graphics.DrawCircle(canvas, width // 2, height // 2, min(width, height) // 2 - 1, white)

    bar_colors = [
        graphics.Color(180, 180, 180),
        graphics.Color(160, 160, 0),
        graphics.Color(0, 140, 140),
        graphics.Color(0, 140, 0),
        graphics.Color(140, 0, 140),
        graphics.Color(140, 0, 0),
        graphics.Color(0, 0, 140),
    ]
    bar_top = height // 3
    bar_bottom = bar_top + height // 3
    bar_width = max(1, width // len(bar_colors))
    for i, color in enumerate(bar_colors):
        x_start = i * bar_width
        x_end = width if i == len(bar_colors) - 1 else x_start + bar_width
        for x in range(x_start, x_end):
            graphics.DrawLine(canvas, x, bar_top, x, bar_bottom, color)

    label_y = height - 3
    label_x = max(0, (width - text_width(label_font, label)) // 2)
    graphics.DrawText(canvas, label_font, label_x, label_y, white, label)

    timestamp = time.strftime("%H:%M:%S")
    clock_x = max(0, width - text_width(clock_font, timestamp) - 1)
    graphics.DrawText(canvas, clock_font, clock_x, clock_font.baseline, white, timestamp)


def main() -> None:
    parser = argparse.ArgumentParser(description="LED matrix idle animation")
    add_matrix_arguments(parser)
    parser.add_argument("--label", default="IDLE", help="Text shown across the bottom of the screen")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _handle_sigterm)

    matrix = build_matrix(args)
    label_font = load_font("6x13.bdf")
    clock_font = load_font("4x6.bdf")
    canvas = matrix.CreateFrameCanvas()

    while not _stop:
        draw_frame(canvas, label_font, clock_font, args.label)
        canvas = matrix.SwapOnVSync(canvas)
        time.sleep(1)

    matrix.Clear()


if __name__ == "__main__":
    main()

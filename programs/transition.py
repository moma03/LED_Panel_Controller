#!/usr/bin/env python3
"""Transition animation: shows the name of the program being switched to, then exits.

Run to completion (blocking) by TransitionManager.switch() between stopping
the old program and starting the new one -- it must exit on its own rather
than loop forever, unlike idle.py.
"""

from __future__ import annotations

import time

from matrix_program import SampleBase, graphics, load_font, text_width


class Transition(SampleBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parser.add_argument("--program-name", default="", help="Display name of the program being switched to")
        self.parser.add_argument("--duration", type=float, default=1.5, help="Seconds to show the message (default: 1.5)")

    def run(self) -> None:
        font = load_font("7x13.bdf")
        canvas = self.matrix.CreateFrameCanvas()
        canvas.Fill(0, 0, 0)

        text = self.args.program_name or "..."
        white = graphics.Color(255, 255, 255)
        x = max(0, (canvas.width - text_width(font, text)) // 2)
        y = (canvas.height + font.height) // 2
        graphics.DrawText(canvas, font, x, y, white, text)
        self.matrix.SwapOnVSync(canvas)

        time.sleep(self.args.duration)
        self.matrix.Clear()


if __name__ == "__main__":
    Transition().process()

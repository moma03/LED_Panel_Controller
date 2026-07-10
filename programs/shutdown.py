#!/usr/bin/env python3
"""Shutdown animation: shows a goodbye message, then exits.

Run to completion (blocking) by TransitionManager.shutdown() before the
active process is stopped and the display PSU relay is switched off.
"""

from __future__ import annotations

import time

from matrix_program import SampleBase, graphics, load_font, text_width


class Shutdown(SampleBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parser.add_argument("--message", default="Goodbye!", help="Message shown before the display powers off")
        self.parser.add_argument("--duration", type=float, default=2.0, help="Seconds to show the message (default: 2.0)")

    def run(self) -> None:
        font = load_font("7x13.bdf")
        canvas = self.matrix.CreateFrameCanvas()
        canvas.Fill(0, 0, 0)

        white = graphics.Color(255, 255, 255)
        x = max(0, (canvas.width - text_width(font, self.args.message)) // 2)
        y = (canvas.height + font.height) // 2
        graphics.DrawText(canvas, font, x, y, white, self.args.message)
        self.matrix.SwapOnVSync(canvas)

        time.sleep(self.args.duration)
        self.matrix.Clear()


if __name__ == "__main__":
    Shutdown().process()

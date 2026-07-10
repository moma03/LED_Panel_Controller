# LED Display Controller

A Python service that owns all state for what's shown on an LED matrix — starting,
stopping, and switching between independent display programs, driven over MQTT with
Home Assistant as the UI. See [setup.md](setup.md) for the full design.

## Setup on the Raspberry Pi

1. Clone with submodules (or run `git submodule update --init --recursive` if already cloned):
   ```
   git clone --recurse-submodules https://github.com/moma03/LED_Panel_Controller.git
   ```
   This pulls in [hzeller/rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix)
   under `third_party/rpi-rgb-led-matrix`, which the `idle`/`transition`/`shutdown`
   display programs in [`programs/`](programs/) use to draw on the matrix.

2. Create a Python virtual environment and activate it:
   ```
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Build and install its Python bindings (one-time, on the Pi itself — this compiles
   a C++ extension against the actual hardware headers, it isn't a pip package):
   ```
   cd third_party/rpi-rgb-led-matrix
   sudo apt-get update && sudo apt-get install python3-dev cython3 -y
   pip install .
   ```

4. Install the controller itself:
   ```
   cd ../../
   pip install -e ".[dev]"
   ```

5. Copy [`config/config.example.yaml`](config/config.example.yaml) to `config.yaml` and
   adjust the relay pin, MQTT broker, and program list for your setup.

6. Run it:
   ```
   python -m led_controller --config config.yaml
   ```

**`rgbmatrix` must be installed into the exact interpreter that runs these scripts.**
Two ways this bites people:
- Step 3's `pip install .` has to run with the venv from step 2 already activated —
  otherwise it installs into system Python instead, and `python -m led_controller`
  from inside the venv won't see it.
- `rgbmatrix` needs root to access the GPIO registers directly, and `sudo` by
  default runs *system* Python, not your venv's, even if the venv is active in
  your shell. Use the venv's own interpreter explicitly:
  `sudo <path-to-venv>/bin/python3 -m led_controller --config config.yaml` (same
  for running `programs/idle.py` etc. directly). If you skip this, you'll get
  `ModuleNotFoundError: No module named 'rgbmatrix'` even though the install
  "worked" — because it worked for a different Python than the one that ran.

## Display programs

`system.idle`, `system.transition`, and `system.shutdown` in `config.yaml` point at
[`programs/idle.py`](programs/idle.py), [`programs/transition.py`](programs/transition.py),
and [`programs/shutdown.py`](programs/shutdown.py):

- **idle** — a retro test-pattern screen (grid, color bars, a circle, a label, and a
  live clock) that runs continuously while the controller is `IDLE` or `ERROR`. It's
  terminated with SIGTERM the moment a real program starts, so it exits its render
  loop promptly on that signal rather than looping forever.
- **transition** — shows the display name of the program being switched to
  (`--program-name` is filled in from the `{program}` placeholder by
  `TransitionManager.switch()`), then exits on its own after `--duration` seconds.
- **shutdown** — shows a goodbye message, then exits, before the display PSU relay
  is switched off.

All three subclass rpi-rgb-led-matrix's own `SampleBase` directly (re-exported by
[`programs/matrix_program.py`](programs/matrix_program.py), which just handles the
import path and a couple of drawing helpers) — every one of its `--led-*` hardware
flags (rows/cols/chain/parallel/GPIO mapping/PWM/etc.) is parsed for free, we don't
redefine that argparse surface ourselves.

### Setting matrix hardware options

Set them once in `config.yaml`'s top-level `matrix:` block, using `RGBMatrixOptions`
attribute names (the same names you'd use constructing one directly in Python —
`rows`, `cols`, `chain_length`, `parallel`, `gpio_slowdown`, `brightness`,
`show_refresh_rate`, etc.):

```yaml
matrix:
  rows: 64
  cols: 128
  chain_length: 2
  parallel: 2
  gpio_slowdown: 1
  show_refresh_rate: true
```

Then reference `{matrix_options}` in any command in `config.yaml` — `system.idle`,
`system.transition`, `system.shutdown`, or any program under `programs:` — and the
controller expands it into the individual `--led-*` flags before running the command:

```
python3 programs/idle.py {matrix_options}
  → python3 programs/idle.py --led-rows=64 --led-cols=128 --led-chain=2 --led-parallel=2 --led-slowdown-gpio=1 --led-show-refresh
```

This works for *any* rpi-rgb-led-matrix-based program, not just ones written against
`SampleBase` — a third-party binary that parses hzeller's standard `--led-*` flags
picks these up the same way `programs/idle.py` does. The mapping from `matrix:`'s
attribute names to CLI flag names lives in `led_controller/config.py`'s
`_MATRIX_VALUE_FLAGS`/`_MATRIX_BOOL_FLAGS` — the two naming schemes genuinely differ
in places (`gpio_slowdown` is `--led-slowdown-gpio`, `chain_length` is `--led-chain`),
so an option you set in `matrix:` needs an entry there; the controller fails fast at
startup with a clear error if you set one it doesn't recognize, rather than silently
producing a broken command on the Pi.

These three can only be run on the Pi with the matrix connected and rgbmatrix
installed — there's no way to render them on a dev machine, so verify them on-device.

## Testing

```
pytest
```

The test suite covers the controller's state machine, process management, config
parsing, relay, and MQTT interface with a mock broker/relay — it doesn't (and can't)
exercise the display programs themselves, since those need real matrix hardware.

## Home Assistant

See [`homeassistant/README.md`](homeassistant/README.md).

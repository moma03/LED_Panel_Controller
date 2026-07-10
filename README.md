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

All three share [`programs/matrix_options.py`](programs/matrix_options.py) for the
`--led-*` hardware flags (rows/cols/chain/parallel/GPIO mapping) and RGBMatrix setup,
so they stay consistent without duplicating that boilerplate per script. Defaults
target a single 64x32 chain on an Adafruit Triple LED Matrix Bonnet
(`--led-gpio-mapping adafruit-hat-pwm`); override per-program in `config.yaml` if your
panel differs.

These three can only be run on the Pi with the matrix connected and the bindings
built — there's no way to render them on a dev machine, so verify them on-device.

## Testing

```
pytest
```

The test suite covers the controller's state machine, process management, config
parsing, relay, and MQTT interface with a mock broker/relay — it doesn't (and can't)
exercise the display programs themselves, since those need real matrix hardware.

## Home Assistant

See [`homeassistant/README.md`](homeassistant/README.md).

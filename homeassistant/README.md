# Home Assistant Setup

Home Assistant is UI-only here (per `setup.md`) — it never manages the controller's
state, it just shows what the controller publishes over MQTT and forwards button
presses back as commands.

Entities are created automatically via **MQTT Discovery**: the controller publishes
retained discovery config messages at startup, generated straight from its own
`config.yaml`. There is nothing to hand-author on the Home Assistant side — no YAML
package, no option lists to keep in sync, no restart required.

## Prerequisites

- The Home Assistant **MQTT integration** is set up (Settings → Devices & Services →
  MQTT) and connected to the same broker the controller uses (`mqtt.host` /
  `mqtt.port` in the controller's `config.yaml`).
- Discovery is enabled, which it is by default for the MQTT integration.

## Install

There isn't one — just start the controller (`python -m led_controller --config
config.yaml`) pointed at the same broker Home Assistant's MQTT integration uses. On
connect, it publishes discovery configs for every entity, and Home Assistant creates
them within a few seconds under one device, **LED Display Controller**:

- `sensor.led_display_status`, `sensor.led_display_current_program`,
  `sensor.led_display_current_subprogram`, `sensor.led_display_last_error`
- `select.led_display_program`, `select.led_display_subprogram` — options are the
  display `name` of each program/subprogram from the controller's config (e.g. "Train
  Board", "Berlin Hbf"), not the config id (`trainboard`, `berlin`); the controller
  resolves either one back to the right program, so `name` just has to be unique
- `button.led_display_power_on`, `button.led_display_start_program`,
  `button.led_display_stop`, `button.led_display_reset`, `button.led_display_shutdown`

There's also `button.led_display_emergency_restart`, published separately by a
standalone watchdog rather than the controller itself — see
[`../deploy/README.md`](../deploy/README.md). It force-restarts the whole controller
process (via systemd) and works even if the controller is completely hung, which is
the point: the controller's own buttons above are handled by the same process that
might be stuck.

Editing `programs:` in the controller's `config.yaml` and restarting the controller
re-publishes the discovery configs, so the `select` option lists stay current
automatically — there's only one place to edit.

## Usage

Pick a program (and, for Train Board, a subprogram) in the two dropdowns, then press
**Start** — from idle or while something else is already running, it's the same
button either way: the controller stops whatever's currently showing and starts the
new one. Pressing a button that isn't valid for the current state is harmless, the
controller just rejects it and publishes a message to `sensor.led_display_last_error`.

## Dashboard

[`lovelace_example.yaml`](lovelace_example.yaml) has a ready-made card layout — paste
it into a dashboard view's raw YAML editor, or use it as a reference for your own.

## How the two-step selection works

An MQTT `select` entity normally fires a command the instant you change it, which
doesn't fit a "pick program and subprogram, then press Start" flow. So the two
selects don't talk to the controller directly — their command/state topic is the same
retained topic (`display/pending/program`, `display/pending/subprogram`), which just
lets them remember what you picked. The Start button reads both selects'
current values via `command_template` and sends them together to the controller only
when pressed.

## Limitations

- **No progress indicator.** `setup.md`'s Home Assistant Integration section mentions
  one, but the controller doesn't publish a progress topic yet — there's nothing to
  wire up on the Home Assistant side until that exists.

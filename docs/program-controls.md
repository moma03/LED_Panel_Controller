# Program controls

A display program can expose its own settings and status to Home Assistant
without speaking MQTT: it describes them in a **manifest**, and the hub
publishes them, stores them, and relays changes to the running program over a
**control channel** it hands the program at launch. No program needs broker
credentials or MQTT code.

```
 Home Assistant ──MQTT──▶ hub (LED_Panel_Controller) ──fd 3, JSON lines──▶ program
                ◀──────── one HA device per program  ◀─────── state ──────
```

Hardware-level settings — power, brightness, matrix options — stay the hub's
own and are never part of a program's controls.

## 1. The manifest

The hub asks each program for its manifest once, at startup, by running the
program's `manifest` command from `config.yaml`:

```yaml
programs:
  hvv_display:
    name: HVV U-Bahn
    command: /path/hvv-display/start.sh {matrix_options}
    manifest: /path/hvv-display/start.sh --manifest
```

The command must print the manifest as JSON on stdout and exit within 10 s
without touching the panel. Generating it (instead of shipping a static file)
lets a program fill in options from its own configuration, e.g. a list of
favourite stations. If the command fails, the program still runs — it just
has no controls, and the hub logs why.

```json
{
  "manifest_version": 1,
  "device": { "id": "hvv_display", "name": "HVV U-Bahn Anzeige", "model": "hvv-display" },
  "controls": [
    { "key": "station", "type": "text",   "name": "Haltestelle", "default": "Barmbek", "max": 80 },
    { "key": "display", "type": "select", "name": "Anzeigetyp",
      "options": ["Untergrund", "Oberirdisch"], "default": "Untergrund" },
    { "key": "announcements", "type": "switch", "name": "Störungsmeldungen", "default": true },
    { "key": "refresh", "type": "button", "name": "Aktualisieren" }
  ],
  "sensors": [
    { "key": "station_name", "name": "Aktuelle Haltestelle" },
    { "key": "last_update", "name": "Letzte Aktualisierung",
      "device_class": "timestamp", "entity_category": "diagnostic" }
  ]
}
```

| field | meaning |
|---|---|
| `device.id` | `[a-z0-9_]+`, unique across programs. Becomes the MQTT topic base, the HA node id and the `unique_id` prefix — **keep it stable**, HA entity ids and automations hang off it |
| `device.name`, `device.model` | shown on the HA device card |
| `controls[]` | settings the user changes. `type`: `text`, `select`, `switch`, `number`, `button` |
| `sensors[]` | read-only values the program reports |
| `key` | `[a-z0-9_]+`, unique within the manifest |
| `name` | entity name in HA |
| `default` | value until the user changes it (not for `button`) |
| `options` | `select`: the allowed values, in order |
| `min`, `max`, `step` | `number`: range; `text`: `max` is the length limit (default 100) |
| `persist` | controls only, default `true`: the value survives restarts |
| `icon`, `entity_category`, `device_class`, `unit_of_measurement`, `mode`, `pattern` | passed to HA as is |

Values on the wire are JSON: `text`/`select` are strings, `switch` is
`true`/`false`, `number` is a number. Sensors are strings or numbers.

## 2. What the hub publishes

Per program, as its own HA device (linked to the hub's device with
`via_device`, so it shows up as "connected via LED Display Controller"):

| topic | |
|---|---|
| `homeassistant/<component>/<id>/<key>/config` | discovery, retained. `unique_id` and `object_id` are `<id>_<key>` |
| `<id>/<key>/set` | commands from HA |
| `<id>/<key>/state` | current value, retained |
| `<id>/settings` | every persisted control as one JSON object, retained |
| `<id>/availability` | `online` while the program runs, else `offline`, retained |

Controls are always available: a setting can be changed while its program is
not running (an automation can pick the station before pressing Start), and
the program gets it when it starts. Sensors and buttons follow
`<id>/availability`, since only a running program can report or react.

**Persistence.** The hub keeps no files. At startup it reads `<id>/settings`
back from the broker (retained) and waits up to 1.5 s for it before publishing
anything for that device, so a restart never overwrites the stored settings
with defaults.

**Validation.** A command that does not fit its control (unknown option,
out of range, too long, control characters) is dropped and the current state
is republished, so HA snaps back.

## 3. The control channel

When the hub launches a program that has a manifest, it creates a Unix
socket pair, passes one end to the program, and sets

```
LED_PANEL_CONTROL_FD=<fd number>
```

The descriptor is inherited through wrapper scripts (`start.sh`,
`run_pair.sh`) like any other. A program that ignores it simply gets no live
updates. Messages are JSON objects, one per line, UTF-8, at most 64 KiB.

**Hub → program**

| message | when |
|---|---|
| `{"type": "settings", "values": {...}}` | first, right after launch: every control's current value |
| `{"type": "set", "key": "display", "value": "Oberirdisch"}` | the user changed a control |
| `{"type": "press", "key": "refresh"}` | a button was pressed |

**Program → hub**

| message | |
|---|---|
| `{"type": "state", "values": {...}}` | sensor values, and controls whose value the program changed itself |

A program reports a control when its effective value differs from what it was
sent — e.g. picking a favourite also sets the station, or a command-line
argument won over the stored setting. The hub then stores and publishes it like
a user change. Unknown keys are ignored.

When the program exits, the channel closes; the hub marks the device offline.

## 4. Subprograms as presets

For a program with controls, a subprogram can carry settings instead of (or as
well as) a `{subprogram}` placeholder in the command:

```yaml
    subprograms:
      hamburg:
        name: Hamburg Hbf
        settings: { station: "8002549" }
```

Starting with that subprogram applies the settings first — they are stored and
published like a change from HA — and then launches the program. Starting
without a subprogram uses whatever is stored. Programs without a manifest keep
using `{subprogram}` exactly as before.

## 5. Writing a program

- **C++** (led-panel-runtime): `led::ControlChannel` in `src/app/control_channel.h`.
- **Python**: `led_controller.program_client.ProgramClient`.

Both read `LED_PANEL_CONTROL_FD`, parse the lines on a thread of their own, and
call you back for `settings`, `set` and `press`; `SendState({...})` reports
values. Print the manifest when started with `--manifest`.

## 6. Dashboard

Each program is its own device, so HA automations can address it directly.
To show a program's controls only while it runs, wrap them in a conditional
card on the hub's current-program sensor (its state is the program id) — see
`homeassistant/lovelace_example.yaml`.

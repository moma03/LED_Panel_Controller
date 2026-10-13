"""Program controls: settings and status a display program exposes to Home
Assistant through the hub -- see docs/program-controls.md.

Each program with a manifest becomes one HA device. The hub owns its entities,
keeps the values (persisted as a retained snapshot on the broker, nothing on
disk), and relays changes to the running program over its control channel.

Three threads touch a ProgramControls: the MQTT network thread (commands from
HA), the controller loop (launch, stop, restore deadline) and the channel's
reader (state from the program). Everything goes through one lock; publishing
is a non-blocking queue operation in paho, so it is fine to do under it.
"""

from __future__ import annotations

import json
import math
import re
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .control_channel import ControlChannel

MANIFEST_VERSION = 1
MANIFEST_TIMEOUT_SECONDS = 10.0
RESTORE_WAIT_SECONDS = 1.5
TEXT_DEFAULT_MAX = 100

CONTROL_TYPES = ("text", "select", "switch", "number", "button")
_KEY_RE = re.compile(r"^[a-z0-9_]+$")
# Optional entity fields handed to Home Assistant unchanged.
_PASSTHROUGH = ("icon", "entity_category", "device_class", "unit_of_measurement", "mode", "pattern")

Publish = Callable[[str, str, bool], None]


class ManifestError(Exception):
    """A manifest that cannot be used. The program then runs without controls."""


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EntitySpec:
    key: str
    kind: str                   # a CONTROL_TYPES entry, or "sensor"
    name: str
    default: Any = None
    options: tuple[str, ...] = ()
    min: float | None = None
    max: float | None = None
    step: float | None = None
    persist: bool = True
    ha: dict = field(default_factory=dict, compare=False)

    @property
    def component(self) -> str:
        return self.kind

    def coerce(self, value: Any) -> Any:
        """Checks a value for this control and returns it normalized. Raises
        ValueError with a message fit for a log line."""
        if self.kind == "switch":
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.upper() in ("ON", "OFF", "TRUE", "FALSE"):
                return value.upper() in ("ON", "TRUE")
            raise ValueError(f"{self.key}: expected on/off, got {value!r}")
        if self.kind == "number":
            if isinstance(value, bool):
                raise ValueError(f"{self.key}: expected a number, got {value!r}")
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{self.key}: expected a number, got {value!r}") from None
            if not math.isfinite(number):
                raise ValueError(f"{self.key}: {value!r} is not a finite number")
            if self.min is not None and number < self.min:
                raise ValueError(f"{self.key}: {number} is below {self.min}")
            if self.max is not None and number > self.max:
                raise ValueError(f"{self.key}: {number} is above {self.max}")
            return int(number) if number.is_integer() else number
        if self.kind in ("text", "select"):
            if not isinstance(value, str):
                raise ValueError(f"{self.key}: expected text, got {value!r}")
            if self.kind == "select":
                if value not in self.options:
                    raise ValueError(f"{self.key}: {value!r} is not one of {list(self.options)}")
                return value
            limit = int(self.max) if self.max is not None else TEXT_DEFAULT_MAX
            if len(value) > limit:
                raise ValueError(f"{self.key}: longer than {limit} characters")
            if any(not ch.isprintable() for ch in value):
                raise ValueError(f"{self.key}: contains control characters")
            return value
        raise ValueError(f"{self.key}: a {self.kind} has no value")

    def to_payload(self, value: Any) -> str:
        if value is None:
            return ""
        if self.kind == "switch":
            return "ON" if value else "OFF"
        return str(value)


@dataclass(frozen=True)
class Manifest:
    device_id: str
    device_name: str
    model: str
    controls: tuple[EntitySpec, ...]
    sensors: tuple[EntitySpec, ...]

    def control(self, key: str) -> EntitySpec | None:
        return next((c for c in self.controls if c.key == key), None)

    def sensor(self, key: str) -> EntitySpec | None:
        return next((s for s in self.sensors if s.key == key), None)


def _entity(raw: Any, kind_hint: str | None, seen: set[str]) -> EntitySpec:
    if not isinstance(raw, dict):
        raise ManifestError("every control and sensor must be a JSON object")
    key = raw.get("key")
    if not isinstance(key, str) or not _KEY_RE.match(key):
        raise ManifestError(f"key {key!r} must match [a-z0-9_]+")
    if key in seen:
        raise ManifestError(f"key {key!r} is used twice")
    seen.add(key)
    kind = kind_hint or raw.get("type")
    if kind not in CONTROL_TYPES + ("sensor",):
        raise ManifestError(f"{key}: type must be one of {', '.join(CONTROL_TYPES)}, got {kind!r}")
    name = raw.get("name", key)
    if not isinstance(name, str) or not name:
        raise ManifestError(f"{key}: name must be a non-empty string")

    options = raw.get("options", [])
    if kind == "select":
        if (not isinstance(options, list) or not options
                or not all(isinstance(o, str) and o for o in options)):
            raise ManifestError(f"{key}: a select needs a non-empty list of options")
        if len(set(options)) != len(options):
            raise ManifestError(f"{key}: options must be unique")

    def number(field_name: str) -> float | None:
        value = raw.get(field_name)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ManifestError(f"{key}: {field_name} must be a number")
        return value

    persist = raw.get("persist", True)
    if not isinstance(persist, bool):
        raise ManifestError(f"{key}: persist must be true or false")

    spec = EntitySpec(
        key=key,
        kind=kind,
        name=name,
        options=tuple(options) if kind == "select" else (),
        min=number("min"),
        max=number("max"),
        step=number("step"),
        persist=persist and kind not in ("button", "sensor"),
        ha={k: raw[k] for k in _PASSTHROUGH if k in raw},
    )

    if kind in ("button", "sensor"):
        if "default" in raw:
            raise ManifestError(f"{key}: a {kind} has no default")
        return spec
    if "default" not in raw:
        default = {"text": "", "select": spec.options[0] if spec.options else None,
                   "switch": False, "number": spec.min if spec.min is not None else 0}[kind]
    else:
        default = raw["default"]
    try:
        default = spec.coerce(default)
    except ValueError as exc:
        raise ManifestError(f"default: {exc}") from None
    return EntitySpec(**{**spec.__dict__, "default": default})


def parse_manifest(data: Any) -> Manifest:
    if isinstance(data, (str, bytes)):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ManifestError(f"not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise ManifestError("the manifest must be a JSON object")
    if data.get("manifest_version") != MANIFEST_VERSION:
        raise ManifestError(f"manifest_version must be {MANIFEST_VERSION}, got "
                            f"{data.get('manifest_version')!r}")
    device = data.get("device")
    if not isinstance(device, dict):
        raise ManifestError("device must be an object")
    device_id = device.get("id")
    if not isinstance(device_id, str) or not _KEY_RE.match(device_id):
        raise ManifestError(f"device.id {device_id!r} must match [a-z0-9_]+")
    seen: set[str] = set()
    controls = data.get("controls", [])
    sensors = data.get("sensors", [])
    if not isinstance(controls, list) or not isinstance(sensors, list):
        raise ManifestError("controls and sensors must be lists")
    parsed_controls = tuple(_entity(c, None, seen) for c in controls)
    if any(c.kind == "sensor" for c in parsed_controls):
        raise ManifestError("sensors belong in 'sensors', not 'controls'")
    return Manifest(
        device_id=device_id,
        device_name=str(device.get("name") or device_id),
        model=str(device.get("model") or device_id),
        controls=parsed_controls,
        sensors=tuple(_entity(s, "sensor", seen) for s in sensors),
    )


def load_manifest(command: str, cwd: str | Path | None = None,
                  timeout: float = MANIFEST_TIMEOUT_SECONDS) -> Manifest:
    """Runs a program's manifest command and parses what it prints."""
    try:
        result = subprocess.run(shlex.split(command), cwd=cwd, capture_output=True,
                                timeout=timeout, text=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ManifestError(f"could not run {command!r}: {exc}") from None
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()[-1:] or ["no output"]
        raise ManifestError(f"{command!r} exited with {result.returncode}: {detail[0]}")
    return parse_manifest(result.stdout)


# ---------------------------------------------------------------------------
# One program's entities and values
# ---------------------------------------------------------------------------

class ProgramControls:
    def __init__(self, program_id: str, manifest: Manifest, publish: Publish,
                 hub_device_id: str, discovery_prefix: str = "homeassistant"):
        self.program_id = program_id
        self.manifest = manifest
        self._publish = publish
        self._hub_device_id = hub_device_id
        self._prefix = discovery_prefix
        self._base = manifest.device_id
        self._lock = threading.RLock()
        self._values: dict[str, Any] = {c.key: c.default for c in manifest.controls
                                         if c.kind != "button"}
        self._sensors: dict[str, Any] = {}
        self._restored = False
        self._restore_deadline: float | None = None
        self._channel: ControlChannel | None = None

    # -- topics --------------------------------------------------------------

    @property
    def settings_topic(self) -> str:
        return f"{self._base}/settings"

    @property
    def availability_topic(self) -> str:
        return f"{self._base}/availability"

    def command_topic(self, key: str) -> str:
        return f"{self._base}/{key}/set"

    def state_topic(self, key: str) -> str:
        return f"{self._base}/{key}/state"

    def subscriptions(self) -> list[str]:
        return [self.settings_topic] + [self.command_topic(c.key) for c in self.manifest.controls]

    # -- discovery -----------------------------------------------------------

    def discovery_messages(self) -> list[tuple[str, str]]:
        device = {
            "identifiers": [self._base],
            "name": self.manifest.device_name,
            "manufacturer": "Custom",
            "model": self.manifest.model,
            "via_device": self._hub_device_id,
        }
        out = []
        for spec in self.manifest.controls + self.manifest.sensors:
            cfg: dict[str, Any] = {
                "name": spec.name,
                "unique_id": f"{self._base}_{spec.key}",
                "object_id": f"{self._base}_{spec.key}",
                "device": device,
                **spec.ha,
            }
            if spec.kind == "button":
                cfg["command_topic"] = self.command_topic(spec.key)
                cfg["payload_press"] = "PRESS"
            elif spec.kind != "sensor":
                cfg["command_topic"] = self.command_topic(spec.key)
                cfg["state_topic"] = self.state_topic(spec.key)
            else:
                cfg["state_topic"] = self.state_topic(spec.key)
            if spec.kind == "select":
                cfg["options"] = list(spec.options)
            elif spec.kind == "switch":
                cfg["payload_on"], cfg["payload_off"] = "ON", "OFF"
                cfg["state_on"], cfg["state_off"] = "ON", "OFF"
            elif spec.kind == "number":
                for k in ("min", "max", "step"):
                    if getattr(spec, k) is not None:
                        cfg[k] = getattr(spec, k)
            elif spec.kind == "text":
                cfg["max"] = int(spec.max) if spec.max is not None else TEXT_DEFAULT_MAX
            # Settings stay usable while the program is off (an automation can
            # pick the station before Start); only a running program can report
            # or act on a button press.
            if spec.kind in ("sensor", "button"):
                cfg["availability_topic"] = self.availability_topic
            out.append((f"{self._prefix}/{spec.component}/{self._base}/{spec.key}/config",
                        json.dumps(cfg, ensure_ascii=False)))
        return out

    # -- MQTT lifecycle --------------------------------------------------------

    def on_connect(self, now: float) -> None:
        with self._lock:
            for topic, payload in self.discovery_messages():
                self._publish(topic, payload, True)
            self._publish(self.availability_topic, "online" if self._channel else "offline", True)
            if self._restored:
                self._publish_all()
            elif self._restore_deadline is None:
                self._restore_deadline = now + RESTORE_WAIT_SECONDS

    def tick(self, now: float) -> None:
        with self._lock:
            if not self._restored and self._restore_deadline is not None and now >= self._restore_deadline:
                self._finish_restore()

    def handle_message(self, topic: str, payload: str) -> bool:
        if topic == self.settings_topic:
            self._restore(payload)
            return True
        prefix, suffix = f"{self._base}/", "/set"
        if not (topic.startswith(prefix) and topic.endswith(suffix)):
            return False
        spec = self.manifest.control(topic[len(prefix):-len(suffix)])
        if spec is None:
            return False
        with self._lock:
            if spec.kind == "button":
                if self._channel is not None:
                    self._channel.send({"type": "press", "key": spec.key})
                return True
            try:
                value = spec.coerce(payload)
            except ValueError as exc:
                print(f"[program-controls] {self.program_id}: rejected from Home Assistant: {exc}",
                      file=sys.stderr)
                # Republish the current value so HA snaps back.
                self._publish(self.state_topic(spec.key), spec.to_payload(self._values[spec.key]), True)
                return True
            self._set(spec, value, tell_program=True)
        return True

    def _restore(self, payload: str) -> None:
        with self._lock:
            if self._restored:
                return  # our own snapshot echoed back
            try:
                snapshot = json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                snapshot = {}
            if isinstance(snapshot, dict):
                for key, value in snapshot.items():
                    spec = self.manifest.control(key)
                    if spec is None or not spec.persist or spec.kind == "button":
                        continue
                    try:
                        self._values[key] = spec.coerce(value)
                    except ValueError as exc:
                        print(f"[program-controls] {self.program_id}: stored value dropped: {exc}",
                              file=sys.stderr)
            self._finish_restore()

    def _finish_restore(self) -> None:
        self._restored = True
        self._publish_all()
        if self._channel is not None:
            # Launched before the snapshot arrived: hand over the restored values.
            self._channel.send({"type": "settings", "values": dict(self._values)})

    # -- values ----------------------------------------------------------------

    def values(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._values)

    def apply_preset(self, settings: dict) -> None:
        """A subprogram's settings, applied before its launch. Raises ValueError
        for keys or values the manifest does not allow."""
        with self._lock:
            checked = []
            for key, value in settings.items():
                spec = self.manifest.control(key)
                if spec is None or spec.kind == "button":
                    raise ValueError(f"{self.program_id} has no setting {key!r}")
                checked.append((spec, spec.coerce(value)))
            for spec, value in checked:
                self._set(spec, value, tell_program=True)

    def _set(self, spec: EntitySpec, value: Any, tell_program: bool) -> None:
        if self._values.get(spec.key) == value:
            return
        self._values[spec.key] = value
        if self._restored:
            self._publish(self.state_topic(spec.key), spec.to_payload(value), True)
            if spec.persist:
                self._publish_snapshot()
        if tell_program and self._channel is not None:
            self._channel.send({"type": "set", "key": spec.key, "value": value})

    def _publish_snapshot(self) -> None:
        snapshot = {c.key: self._values[c.key] for c in self.manifest.controls if c.persist}
        self._publish(self.settings_topic, json.dumps(snapshot, ensure_ascii=False), True)

    def _publish_all(self) -> None:
        for spec in self.manifest.controls:
            if spec.kind != "button":
                self._publish(self.state_topic(spec.key), spec.to_payload(self._values[spec.key]), True)
        for key, value in self._sensors.items():
            self._publish(self.state_topic(key), self.manifest.sensor(key).to_payload(value), True)
        self._publish_snapshot()

    # -- the running program ---------------------------------------------------

    def attach(self, channel: ControlChannel) -> None:
        """Called right after the program was launched with `channel`."""
        with self._lock:
            self._channel = channel
            channel.send({"type": "settings", "values": dict(self._values)})
            self._publish(self.availability_topic, "online", True)
        channel.start(self._on_program_message)

    def detach(self) -> None:
        with self._lock:
            channel, self._channel = self._channel, None
            self._publish(self.availability_topic, "offline", True)
        if channel is not None:
            channel.close()

    @property
    def running(self) -> bool:
        return self._channel is not None

    def _on_program_message(self, message: dict) -> None:
        if message.get("type") != "state" or not isinstance(message.get("values"), dict):
            return
        with self._lock:
            for key, value in message["values"].items():
                control = self.manifest.control(key)
                if control is not None and control.kind != "button":
                    try:
                        self._set(control, control.coerce(value), tell_program=False)
                    except ValueError as exc:
                        print(f"[program-controls] {self.program_id}: bad state from program: {exc}",
                              file=sys.stderr)
                    continue
                sensor = self.manifest.sensor(key)
                if sensor is None:
                    continue
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                if self._sensors.get(key) == value and key in self._sensors:
                    continue
                self._sensors[key] = value
                if self._restored:
                    self._publish(self.state_topic(key), sensor.to_payload(value), True)


# ---------------------------------------------------------------------------
# All programs
# ---------------------------------------------------------------------------

class ControlsHub:
    def __init__(self, programs: dict[str, ProgramControls] | None = None):
        self.programs: dict[str, ProgramControls] = programs or {}

    @classmethod
    def build(cls, manifest_commands: dict[str, str], publish: Publish, hub_device_id: str,
              cwd: str | Path | None = None,
              loader: Callable[..., Manifest] = load_manifest) -> "ControlsHub":
        """Loads every program's manifest. A program whose manifest cannot be
        loaded runs without controls; the reason is logged, startup goes on."""
        programs: dict[str, ProgramControls] = {}
        device_ids: dict[str, str] = {}
        for program_id, command in manifest_commands.items():
            try:
                manifest = loader(command, cwd=cwd)
            except ManifestError as exc:
                print(f"[program-controls] {program_id}: no controls -- {exc}", file=sys.stderr)
                continue
            if manifest.device_id in device_ids:
                print(f"[program-controls] {program_id}: no controls -- device id "
                      f"{manifest.device_id!r} is already used by {device_ids[manifest.device_id]}",
                      file=sys.stderr)
                continue
            device_ids[manifest.device_id] = program_id
            programs[program_id] = ProgramControls(program_id, manifest, publish, hub_device_id)
            print(f"[program-controls] {program_id}: {len(manifest.controls)} controls, "
                  f"{len(manifest.sensors)} sensors as device {manifest.device_id!r}")
        return cls(programs)

    def get(self, program_id: str | None) -> ProgramControls | None:
        return self.programs.get(program_id) if program_id else None

    def subscriptions(self) -> list[str]:
        return [t for p in self.programs.values() for t in p.subscriptions()]

    def on_connect(self) -> None:
        now = time.monotonic()
        for p in self.programs.values():
            p.on_connect(now)

    def handle_message(self, topic: str, payload: str) -> bool:
        return any(p.handle_message(topic, payload) for p in self.programs.values())

    def tick(self) -> None:
        now = time.monotonic()
        for p in self.programs.values():
            p.tick(now)

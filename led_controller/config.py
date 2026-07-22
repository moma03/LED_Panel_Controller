"""Loads and validates the YAML configuration described in setup.md.

Validation happens once, at startup, so a bad config fails fast with a clear
error instead of surfacing as a runtime crash mid-transition.
"""

from __future__ import annotations

import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Raised for any structurally or semantically invalid config file."""


@dataclass(frozen=True)
class Subprogram:
    id: str
    name: str


@dataclass(frozen=True)
class Program:
    id: str
    name: str
    command: str
    subprograms: dict[str, Subprogram] = field(default_factory=dict)

    def resolve_subprogram(self, key: str | None) -> Subprogram | None:
        """Looks up a subprogram by its id (the subprograms: dict key) or by its
        display `name` -- Home Assistant's select shows the friendly name rather than
        the raw id (see mqtt_interface.py's _select_configs), so whichever one an MQTT
        client actually sends back must resolve to the same subprogram."""
        if key is None:
            return None
        if key in self.subprograms:
            return self.subprograms[key]
        for subprogram in self.subprograms.values():
            if subprogram.name == key:
                return subprogram
        return None

    def resolve_command(self, subprogram_id: str | None) -> str:
        """Substitute the {subprogram} placeholder, rejecting unknown subprograms."""
        if "{subprogram}" not in self.command:
            return self.command
        subprogram = self.resolve_subprogram(subprogram_id)
        if subprogram is None:
            raise ConfigError(
                f"program '{self.id}' requires a known subprogram, got {subprogram_id!r}"
            )
        return self.command.replace("{subprogram}", subprogram.id)


@dataclass(frozen=True)
class SystemConfig:
    """Commands for the controller's own animations — not user-selectable programs."""

    idle: str
    shutdown: str


@dataclass(frozen=True)
class RelayConfig:
    backend: str = "mock"  # "gpio" or "mock"
    # BCM numbering. GPIO0/1 (physical pins 27/28, the HAT ID EEPROM pins) are the only
    # pins not claimed by any of the 3 parallel chains in rpi-rgb-led-matrix's "regular"
    # mapping (which Adafruit's bonnets use) — everything from GPIO2-27 is a matrix signal
    # on at least one chain. Verify against your specific bonnet/HAT before wiring.
    pin: int = 0
    # Most cheap relay boards are active-low (LOW energizes the relay) -- set this to
    # match the board actually wired up so on()/off() drive the physical PSU state
    # they claim to, instead of energizing it the moment the GPIO pin is initialized.
    active_low: bool = False


# Maps config.yaml's matrix: block keys (RGBMatrixOptions attribute names, so the
# same names you'd use constructing one directly in Python) to the --led-* CLI flags
# rpi-rgb-led-matrix's own SampleBase (and any program built against it, ours or
# third-party) already parses for free. The two naming schemes genuinely differ in
# places -- gpio_slowdown is --led-slowdown-gpio, chain_length is --led-chain -- so
# this table exists to bridge them; it needs a new entry if upstream adds an option
# you want to expose here. Source: rpi-rgb-led-matrix's
# bindings/python/samples/samplebase.py.
_MATRIX_VALUE_FLAGS: dict[str, str] = {
    "rows": "--led-rows",
    "cols": "--led-cols",
    "chain_length": "--led-chain",
    "parallel": "--led-parallel",
    "hardware_mapping": "--led-gpio-mapping",
    "row_address_type": "--led-row-addr-type",
    "multiplexing": "--led-multiplexing",
    "pwm_bits": "--led-pwm-bits",
    "brightness": "--led-brightness",
    "pwm_lsb_nanoseconds": "--led-pwm-lsb-nanoseconds",
    "led_rgb_sequence": "--led-rgb-sequence",
    "pixel_mapper_config": "--led-pixel-mapper",
    "panel_type": "--led-panel-type",
    "pwm_dither_bits": "--led-pwm-dither-bits",
    "limit_refresh_rate_hz": "--led-limit-refresh",
    "gpio_slowdown": "--led-slowdown-gpio",
    "rp1_pio": "--led-rp1-pio",
}

# Boolean attributes map to a bare CLI flag, emitted only when the config value
# equals the trigger (drop_privileges is inverted: the flag disables the default).
_MATRIX_BOOL_FLAGS: dict[str, tuple[str, bool]] = {
    "show_refresh_rate": ("--led-show-refresh", True),
    "disable_hardware_pulsing": ("--led-no-hardware-pulse", True),
    "drop_privileges": ("--led-no-drop-privs", False),
}


@dataclass(frozen=True)
class MatrixConfig:
    """RGBMatrixOptions attribute overrides from config.yaml's `matrix:` block,
    rendered into the individual --led-* flags any rpi-rgb-led-matrix-based program
    expects -- see _MATRIX_VALUE_FLAGS/_MATRIX_BOOL_FLAGS above."""

    options: dict[str, Any] = field(default_factory=dict)

    def as_cli_args(self) -> str:
        parts = []
        for key, value in self.options.items():
            if key in _MATRIX_BOOL_FLAGS:
                flag, trigger = _MATRIX_BOOL_FLAGS[key]
                if value == trigger:
                    parts.append(flag)
            elif key in _MATRIX_VALUE_FLAGS:
                parts.append(shlex.quote(f"{_MATRIX_VALUE_FLAGS[key]}={value}"))
            else:
                raise ConfigError(
                    f"unknown matrix option {key!r} -- see led_controller/config.py's "
                    "_MATRIX_VALUE_FLAGS/_MATRIX_BOOL_FLAGS"
                )
        return " ".join(parts)


@dataclass(frozen=True)
class AppConfig:
    programs: dict[str, Program]
    system: SystemConfig
    relay: RelayConfig
    matrix: MatrixConfig = field(default_factory=MatrixConfig)
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    process_terminate_timeout: float = 5.0

    def render_command(self, command: str) -> str:
        """Substitutes the {matrix_options} and {python} placeholders.

        {python} expands to sys.executable -- the exact interpreter running the
        controller right now, venv and all. A bare "python3" in a command is
        resolved via the child process's $PATH at launch time, which is *not*
        guaranteed to be the same interpreter the controller itself is running
        under (rgbmatrix must be installed into that specific interpreter -- see
        README.md): a systemd unit's minimal $PATH in particular usually doesn't
        include a venv's bin/ directory, so a bare "python3" there silently falls
        back to system Python and whatever (possibly stale, possibly missing
        rgbmatrix entirely) packages happen to be installed there instead."""
        if "{python}" in command:
            command = command.replace("{python}", sys.executable)
        if "{matrix_options}" not in command:
            return command
        return command.replace("{matrix_options}", self.matrix.as_cli_args())

    def resolve_program(self, key: str | None) -> Program | None:
        """Looks up a program by its id (the programs: dict key) or by its display
        `name` -- same reasoning as Program.resolve_subprogram above."""
        if key is None:
            return None
        if key in self.programs:
            return self.programs[key]
        for program in self.programs.values():
            if program.name == key:
                return program
        return None


def _load_subprograms(raw: dict, program_id: str) -> dict[str, Subprogram]:
    subprograms: dict[str, Subprogram] = {}
    for sub_id, sub_raw in (raw or {}).items():
        if "name" not in sub_raw:
            raise ConfigError(f"program '{program_id}' subprogram '{sub_id}' missing 'name'")
        subprograms[sub_id] = Subprogram(id=sub_id, name=sub_raw["name"])
    return subprograms


def _load_programs(raw: dict) -> dict[str, Program]:
    if not raw:
        raise ConfigError("config must define at least one program under 'programs'")
    programs: dict[str, Program] = {}
    for prog_id, prog_raw in raw.items():
        for required in ("name", "command"):
            if required not in prog_raw:
                raise ConfigError(f"program '{prog_id}' missing required field '{required}'")
        programs[prog_id] = Program(
            id=prog_id,
            name=prog_raw["name"],
            command=prog_raw["command"],
            subprograms=_load_subprograms(prog_raw.get("subprograms"), prog_id),
        )
    _check_unique_names(
        [p.name for p in programs.values()],
        "program 'name' values must be unique -- Home Assistant's program select resolves by name",
    )
    _check_unique_names(
        [sub.name for p in programs.values() for sub in p.subprograms.values()],
        "subprogram 'name' values must be unique across all programs -- Home Assistant's "
        "subprogram select is a single dropdown shared by every program and resolves by name",
    )
    return programs


def _check_unique_names(names: list[str], message: str) -> None:
    seen = set()
    for name in names:
        if name in seen:
            raise ConfigError(f"{message} (duplicate: {name!r})")
        seen.add(name)


def _load_system(raw: dict) -> SystemConfig:
    if not raw:
        raise ConfigError("config must define a 'system' block with idle/shutdown commands")
    for required in ("idle", "shutdown"):
        if required not in raw:
            raise ConfigError(f"'system' block missing required field '{required}'")
    return SystemConfig(idle=raw["idle"], shutdown=raw["shutdown"])


def _load_relay(raw: dict | None) -> RelayConfig:
    raw = raw or {}
    backend = raw.get("backend", "mock")
    if backend not in ("gpio", "mock"):
        raise ConfigError(f"relay.backend must be 'gpio' or 'mock', got {backend!r}")
    return RelayConfig(backend=backend, pin=raw.get("pin", 0), active_low=bool(raw.get("active_low", False)))


def _load_matrix(raw: dict | None) -> MatrixConfig:
    options = raw or {}
    known = set(_MATRIX_VALUE_FLAGS) | set(_MATRIX_BOOL_FLAGS)
    unknown = sorted(set(options) - known)
    if unknown:
        raise ConfigError(
            f"unknown matrix option(s) {unknown} -- see led_controller/config.py's "
            "_MATRIX_VALUE_FLAGS/_MATRIX_BOOL_FLAGS for supported RGBMatrixOptions attributes"
        )
    return MatrixConfig(options=options)


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text())
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"config file {path} must contain a YAML mapping at the top level")

    mqtt_raw = raw.get("mqtt", {})

    return AppConfig(
        programs=_load_programs(raw.get("programs")),
        system=_load_system(raw.get("system")),
        relay=_load_relay(raw.get("relay")),
        matrix=_load_matrix(raw.get("matrix")),
        mqtt_host=mqtt_raw.get("host", "localhost"),
        mqtt_port=mqtt_raw.get("port", 1883),
        mqtt_username=mqtt_raw.get("username"),
        mqtt_password=mqtt_raw.get("password"),
        process_terminate_timeout=float(raw.get("process_terminate_timeout", 5.0)),
    )

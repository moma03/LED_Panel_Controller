"""Loads and validates the YAML configuration described in setup.md.

Validation happens once, at startup, so a bad config fails fast with a clear
error instead of surfacing as a runtime crash mid-transition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

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

    def resolve_command(self, subprogram_id: str | None) -> str:
        """Substitute the {subprogram} placeholder, rejecting unknown subprograms."""
        if "{subprogram}" not in self.command:
            return self.command
        if subprogram_id is None or subprogram_id not in self.subprograms:
            raise ConfigError(
                f"program '{self.id}' requires a known subprogram, got {subprogram_id!r}"
            )
        return self.command.replace("{subprogram}", subprogram_id)


@dataclass(frozen=True)
class SystemConfig:
    """Commands for the controller's own animations — not user-selectable programs."""

    idle: str
    transition: str
    shutdown: str

    def resolve_transition_command(self, target_program_name: str) -> str:
        """Substitutes the {program} placeholder with the display name of the
        program being switched to. Optional: commands without the placeholder
        are returned unchanged, same as Program.resolve_command's {subprogram}."""
        if "{program}" not in self.transition:
            return self.transition
        return self.transition.replace("{program}", target_program_name)


@dataclass(frozen=True)
class RelayConfig:
    backend: str = "mock"  # "gpio" or "mock"
    # BCM numbering. GPIO0/1 (physical pins 27/28, the HAT ID EEPROM pins) are the only
    # pins not claimed by any of the 3 parallel chains in rpi-rgb-led-matrix's "regular"
    # mapping (which Adafruit's bonnets use) — everything from GPIO2-27 is a matrix signal
    # on at least one chain. Verify against your specific bonnet/HAT before wiring.
    pin: int = 0


@dataclass(frozen=True)
class AppConfig:
    programs: dict[str, Program]
    system: SystemConfig
    relay: RelayConfig
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    process_terminate_timeout: float = 5.0


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
    return programs


def _load_system(raw: dict) -> SystemConfig:
    if not raw:
        raise ConfigError("config must define a 'system' block with idle/transition/shutdown commands")
    for required in ("idle", "transition", "shutdown"):
        if required not in raw:
            raise ConfigError(f"'system' block missing required field '{required}'")
    return SystemConfig(idle=raw["idle"], transition=raw["transition"], shutdown=raw["shutdown"])


def _load_relay(raw: dict | None) -> RelayConfig:
    raw = raw or {}
    backend = raw.get("backend", "mock")
    if backend not in ("gpio", "mock"):
        raise ConfigError(f"relay.backend must be 'gpio' or 'mock', got {backend!r}")
    return RelayConfig(backend=backend, pin=raw.get("pin", 0))


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
        mqtt_host=mqtt_raw.get("host", "localhost"),
        mqtt_port=mqtt_raw.get("port", 1883),
        process_terminate_timeout=float(raw.get("process_terminate_timeout", 5.0)),
    )

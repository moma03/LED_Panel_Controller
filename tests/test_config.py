from __future__ import annotations

import pytest

from led_controller.config import ConfigError, SystemConfig, load_config

VALID_YAML = """
system:
  idle: python3 idle.py
  transition: python3 transition.py
  shutdown: python3 shutdown.py

programs:
  weather:
    name: Weather
    command: python3 weather.py

  trainboard:
    name: Train Board
    command: python3 trainboard.py --station {subprogram}
    subprograms:
      berlin:
        name: Berlin Hbf
"""


def write(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text)
    return path


def test_loads_valid_config(tmp_path):
    config = load_config(write(tmp_path, VALID_YAML))
    assert set(config.programs) == {"weather", "trainboard"}
    assert config.programs["trainboard"].subprograms["berlin"].name == "Berlin Hbf"
    assert config.system.idle == "python3 idle.py"
    assert config.relay.backend == "mock"
    assert config.relay.pin == 0


def test_missing_file_raises_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "does-not-exist.yaml")


def test_mqtt_credentials_default_to_none(tmp_path):
    config = load_config(write(tmp_path, VALID_YAML))
    assert config.mqtt_username is None
    assert config.mqtt_password is None


def test_mqtt_credentials_are_parsed(tmp_path):
    text = VALID_YAML + "\nmqtt:\n  host: broker.local\n  username: led-controller\n  password: secret\n"
    config = load_config(write(tmp_path, text))
    assert config.mqtt_host == "broker.local"
    assert config.mqtt_username == "led-controller"
    assert config.mqtt_password == "secret"


def test_missing_programs_raises(tmp_path):
    text = "system:\n  idle: a\n  transition: b\n  shutdown: c\n"
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, text))


def test_missing_system_block_raises(tmp_path):
    text = "programs:\n  weather:\n    name: Weather\n    command: python3 weather.py\n"
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, text))


def test_program_missing_command_raises(tmp_path):
    text = VALID_YAML.replace("command: python3 weather.py", "")
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, text))


def test_resolve_command_substitutes_subprogram(tmp_path):
    config = load_config(write(tmp_path, VALID_YAML))
    command = config.programs["trainboard"].resolve_command("berlin")
    assert command == "python3 trainboard.py --station berlin"


def test_resolve_command_rejects_unknown_subprogram(tmp_path):
    config = load_config(write(tmp_path, VALID_YAML))
    with pytest.raises(ConfigError):
        config.programs["trainboard"].resolve_command("nonexistent")


def test_resolve_command_rejects_missing_subprogram(tmp_path):
    config = load_config(write(tmp_path, VALID_YAML))
    with pytest.raises(ConfigError):
        config.programs["trainboard"].resolve_command(None)


def test_relay_backend_override(tmp_path):
    text = VALID_YAML + "\nrelay:\n  backend: gpio\n  pin: 5\n"
    config = load_config(write(tmp_path, text))
    assert config.relay.backend == "gpio"
    assert config.relay.pin == 5


def test_invalid_relay_backend_raises(tmp_path):
    text = VALID_YAML + "\nrelay:\n  backend: nonsense\n"
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, text))


def test_resolve_transition_command_substitutes_program_name():
    system = SystemConfig(
        idle="python3 idle.py",
        transition='python3 transition.py --program-name "{program}"',
        shutdown="python3 shutdown.py",
    )
    assert system.resolve_transition_command("Weather") == 'python3 transition.py --program-name "Weather"'


def test_resolve_transition_command_without_placeholder_is_unchanged():
    system = SystemConfig(idle="a", transition="python3 transition.py", shutdown="c")
    assert system.resolve_transition_command("Weather") == "python3 transition.py"

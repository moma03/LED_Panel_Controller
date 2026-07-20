from __future__ import annotations

import json
import queue

from led_controller.mqtt_interface import MQTTInterface
from tests.conftest import FakeMQTTClient, make_config


def build_interface(connect_reason_code: int = 0):
    client = FakeMQTTClient(connect_reason_code=connect_reason_code)
    q: "queue.Queue" = queue.Queue()
    return MQTTInterface(client, q), client


def test_successful_connect_subscribes_to_control_topics():
    mqtt, client = build_interface(connect_reason_code=0)
    mqtt.start("localhost", 1883)
    assert set(client.subscribed_topics) == {
        "display/control/power_on",
        "display/control/start",
        "display/control/stop",
        "display/control/reset",
        "display/control/shutdown",
    }


def test_failed_connect_does_not_subscribe(capsys):
    mqtt, client = build_interface(connect_reason_code=5)  # 5 = Not authorized
    mqtt.start("localhost", 1883)
    assert client.subscribed_topics == []
    assert "MQTT connection failed" in capsys.readouterr().err


def test_publish_error_is_also_printed_to_stderr(capsys):
    mqtt, client = build_interface()
    mqtt.publish_error("something went wrong")
    assert "something went wrong" in capsys.readouterr().err
    assert ("display/errors", '{"message": "something went wrong"}', False) in client.published


def discovery_messages(client):
    return [
        (topic, json.loads(payload), retain)
        for topic, payload, retain in client.published
        if topic.startswith("homeassistant/")
    ]


def test_publish_discovery_covers_all_expected_entities():
    mqtt, client = build_interface()
    mqtt.publish_discovery(make_config())
    topics = {topic for topic, _, _ in discovery_messages(client)}
    assert topics == {
        "homeassistant/sensor/led_display_controller/status/config",
        "homeassistant/sensor/led_display_controller/current_program/config",
        "homeassistant/sensor/led_display_controller/current_subprogram/config",
        "homeassistant/sensor/led_display_controller/last_error/config",
        "homeassistant/select/led_display_controller/program/config",
        "homeassistant/select/led_display_controller/subprogram/config",
        "homeassistant/button/led_display_controller/power_on/config",
        "homeassistant/button/led_display_controller/start_program/config",
        "homeassistant/button/led_display_controller/stop/config",
        "homeassistant/button/led_display_controller/reset/config",
        "homeassistant/button/led_display_controller/shutdown/config",
    }


def test_discovery_messages_are_retained():
    mqtt, client = build_interface()
    mqtt.publish_discovery(make_config())
    assert all(retain for _, _, retain in discovery_messages(client))


def test_program_select_options_show_display_names_not_ids():
    mqtt, client = build_interface()
    mqtt.publish_discovery(make_config())
    _, payload, _ = next(m for m in discovery_messages(client) if "select/led_display_controller/program/" in m[0])
    assert set(payload["options"]) == {"OK", "Fail", "Train Board"}


def test_subprogram_select_options_show_display_names_not_ids():
    mqtt, client = build_interface()
    mqtt.publish_discovery(make_config())
    _, payload, _ = next(m for m in discovery_messages(client) if "select/led_display_controller/subprogram" in m[0])
    assert set(payload["options"]) == {"none", "Berlin Hbf"}


def test_all_entities_share_the_same_device():
    mqtt, client = build_interface()
    mqtt.publish_discovery(make_config())
    devices = {json.dumps(payload["device"], sort_keys=True) for _, payload, _ in discovery_messages(client)}
    assert len(devices) == 1


def test_start_button_reads_both_selects():
    mqtt, client = build_interface()
    mqtt.publish_discovery(make_config())
    start = next(m for m in discovery_messages(client) if "start_program" in m[0])[1]
    assert "select.led_display_program" in start["command_template"]
    assert "select.led_display_subprogram" in start["command_template"]


def test_program_and_subprogram_selects_have_explicit_object_id():
    # Without this, Home Assistant slugifies its own entity_id from `name`, which can
    # produce something other than select.led_display_program/subprogram -- exactly
    # what the buttons' command_template above hardcodes and depends on.
    mqtt, client = build_interface()
    mqtt.publish_discovery(make_config())
    program_select = next(m for m in discovery_messages(client) if "select/led_display_controller/program/" in m[0])[1]
    subprogram_select = next(m for m in discovery_messages(client) if "select/led_display_controller/subprogram" in m[0])[1]
    assert program_select["object_id"] == "led_display_program"
    assert subprogram_select["object_id"] == "led_display_subprogram"


def test_every_discovery_entity_has_an_object_id():
    mqtt, client = build_interface()
    mqtt.publish_discovery(make_config())
    for topic, payload, _ in discovery_messages(client):
        assert "object_id" in payload, f"{topic} is missing object_id"
        assert payload["object_id"].startswith("led_display_")

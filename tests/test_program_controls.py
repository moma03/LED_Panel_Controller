from __future__ import annotations

import json
import sys
import time

import pytest

from led_controller.config import AppConfig, Program, RelayConfig, Subprogram, SystemConfig
from led_controller.control_channel import ControlChannel
from led_controller.process_manager import ProcessManager
from led_controller.program_controls import (
    RESTORE_WAIT_SECONDS,
    ControlsHub,
    ManifestError,
    ProgramControls,
    load_manifest,
    parse_manifest,
)

MANIFEST = {
    "manifest_version": 1,
    "device": {"id": "hvv_display", "name": "HVV U-Bahn Anzeige", "model": "hvv-display"},
    "controls": [
        {"key": "station", "type": "text", "name": "Haltestelle", "default": "Barmbek", "max": 80,
         "icon": "mdi:subway-variant"},
        {"key": "display", "type": "select", "name": "Anzeigetyp",
         "options": ["Untergrund", "Oberirdisch"], "default": "Untergrund"},
        {"key": "announcements", "type": "switch", "name": "Störungsmeldungen", "default": True},
        {"key": "rows", "type": "number", "name": "Zeilen", "min": 1, "max": 4, "default": 2},
        {"key": "refresh", "type": "button", "name": "Aktualisieren"},
        {"key": "favorite", "type": "select", "name": "Favorit", "options": ["–", "Barmbek"],
         "persist": False},
    ],
    "sensors": [
        {"key": "station_name", "name": "Aktuelle Haltestelle"},
        {"key": "last_update", "name": "Letzte Aktualisierung", "device_class": "timestamp",
         "entity_category": "diagnostic"},
    ],
}


class Recorder:
    def __init__(self):
        self.published: list[tuple[str, str, bool]] = []

    def __call__(self, topic, payload, retain):
        self.published.append((topic, payload, retain))

    def last(self, topic):
        return next((p for t, p, _ in reversed(self.published) if t == topic), None)

    def topics(self):
        return [t for t, _, _ in self.published]


class FakeChannel:
    def __init__(self):
        self.sent: list[dict] = []
        self.on_message = None
        self.closed = False

    def send(self, message):
        self.sent.append(message)
        return True

    def start(self, on_message, on_close=None):
        self.on_message = on_message

    def close(self):
        self.closed = True


def make(manifest=MANIFEST):
    rec = Recorder()
    pc = ProgramControls("hvv", parse_manifest(manifest), rec, "led_display_controller")
    return pc, rec


def restored(pc, snapshot=None):
    pc.on_connect(now=0.0)
    if snapshot is None:
        pc.tick(now=RESTORE_WAIT_SECONDS + 1)
    else:
        pc.handle_message("hvv_display/settings", json.dumps(snapshot))


# -- manifest ------------------------------------------------------------------

def test_manifest_defaults_and_types():
    m = parse_manifest(MANIFEST)
    assert m.device_id == "hvv_display"
    assert m.control("station").default == "Barmbek"
    assert m.control("announcements").default is True
    assert m.control("favorite").default == "–"  # first option when not given
    assert m.control("rows").default == 2
    assert m.control("refresh").persist is False


@pytest.mark.parametrize("mutate, message", [
    (lambda m: m.update(manifest_version=2), "manifest_version"),
    (lambda m: m["device"].update(id="HVV Display"), "device.id"),
    (lambda m: m["controls"].append({"key": "station", "type": "text"}), "twice"),
    (lambda m: m["controls"].append({"key": "x", "type": "slider"}), "type"),
    (lambda m: m["controls"].append({"key": "x", "type": "select", "options": []}), "options"),
    (lambda m: m["controls"].append({"key": "x", "type": "select", "options": ["a"],
                                     "default": "b"}), "default"),
    (lambda m: m["controls"].append({"key": "x", "type": "button", "default": 1}), "default"),
    (lambda m: m["sensors"].append({"key": "station"}), "twice"),
])
def test_invalid_manifests_are_rejected(mutate, message):
    data = json.loads(json.dumps(MANIFEST))
    mutate(data)
    with pytest.raises(ManifestError, match=message):
        parse_manifest(data)


def test_load_manifest_runs_the_command():
    command = f"{sys.executable} -c \"import json; print(json.dumps({MANIFEST!r}))\""
    # repr() of the dict is valid Python, so the child prints it back as JSON.
    assert load_manifest(command).device_id == "hvv_display"


def test_load_manifest_reports_a_failing_command():
    with pytest.raises(ManifestError, match="exited with 3"):
        load_manifest(f'{sys.executable} -c "import sys; sys.exit(3)"')


def test_hub_skips_programs_whose_manifest_fails(capsys):
    def loader(command, cwd=None):
        if command == "bad":
            raise ManifestError("nope")
        return parse_manifest(MANIFEST)

    hub = ControlsHub.build({"good": "ok", "bad": "bad"}, Recorder(), "hub", loader=loader)
    assert set(hub.programs) == {"good"}
    assert "bad: no controls -- nope" in capsys.readouterr().err


def test_hub_rejects_a_second_program_with_the_same_device_id(capsys):
    hub = ControlsHub.build({"a": "x", "b": "y"}, Recorder(), "hub",
                            loader=lambda c, cwd=None: parse_manifest(MANIFEST))
    assert set(hub.programs) == {"a"}
    assert "already used by a" in capsys.readouterr().err


# -- discovery -------------------------------------------------------------------

def discovery(pc):
    return {topic: json.loads(payload) for topic, payload in pc.discovery_messages()}


def test_discovery_keeps_hvv_entity_ids_and_links_to_the_hub():
    d = discovery(make()[0])
    station = d["homeassistant/text/hvv_display/station/config"]
    # Same unique_id/object_id scheme hvv-display used itself, so HA keeps the
    # entities (and the automations using them) across the migration.
    assert station["unique_id"] == station["object_id"] == "hvv_display_station"
    assert station["command_topic"] == "hvv_display/station/set"
    assert station["state_topic"] == "hvv_display/station/state"
    assert station["max"] == 80
    assert station["icon"] == "mdi:subway-variant"
    assert station["device"]["identifiers"] == ["hvv_display"]
    assert station["device"]["via_device"] == "led_display_controller"


def test_controls_are_always_available_sensors_and_buttons_follow_the_program():
    d = discovery(make()[0])
    assert "availability_topic" not in d["homeassistant/text/hvv_display/station/config"]
    assert "availability_topic" not in d["homeassistant/select/hvv_display/display/config"]
    for t in ("sensor/hvv_display/station_name", "button/hvv_display/refresh"):
        assert d[f"homeassistant/{t}/config"]["availability_topic"] == "hvv_display/availability"


def test_discovery_shapes_per_type():
    d = discovery(make()[0])
    assert d["homeassistant/select/hvv_display/display/config"]["options"] == ["Untergrund", "Oberirdisch"]
    sw = d["homeassistant/switch/hvv_display/announcements/config"]
    assert (sw["payload_on"], sw["payload_off"]) == ("ON", "OFF")
    num = d["homeassistant/number/hvv_display/rows/config"]
    assert (num["min"], num["max"]) == (1, 4)
    button = d["homeassistant/button/hvv_display/refresh/config"]
    assert button["payload_press"] == "PRESS" and "state_topic" not in button
    ts = d["homeassistant/sensor/hvv_display/last_update/config"]
    assert ts["device_class"] == "timestamp" and ts["entity_category"] == "diagnostic"


# -- restore and persistence -------------------------------------------------------

def test_no_state_is_published_before_the_snapshot_had_its_chance():
    pc, rec = make()
    pc.on_connect(now=0.0)
    assert not any(t.endswith("/state") or t.endswith("/settings") for t in rec.topics())
    pc.tick(now=RESTORE_WAIT_SECONDS / 2)
    assert rec.last("hvv_display/station/state") is None
    pc.tick(now=RESTORE_WAIT_SECONDS + 0.1)
    assert rec.last("hvv_display/station/state") == "Barmbek"
    assert json.loads(rec.last("hvv_display/settings"))["station"] == "Barmbek"


def test_retained_snapshot_restores_settings():
    pc, rec = make()
    restored(pc, {"station": "Schlump", "display": "Oberirdisch", "announcements": False,
                  "rows": 3, "unknown": 1, "favorite": "Barmbek"})
    assert pc.values()["station"] == "Schlump"
    assert pc.values()["announcements"] is False
    assert pc.values()["favorite"] == "–"  # persist: false is not restored
    assert rec.last("hvv_display/announcements/state") == "OFF"
    snapshot = json.loads(rec.last("hvv_display/settings"))
    assert "favorite" not in snapshot and snapshot["rows"] == 3


def test_bad_values_in_the_snapshot_are_dropped():
    pc, _ = make()
    restored(pc, {"display": "Kaputt", "station": "Schlump"})
    assert pc.values()["display"] == "Untergrund"
    assert pc.values()["station"] == "Schlump"


def test_own_snapshot_echo_after_restore_is_ignored():
    pc, _ = make()
    restored(pc)
    pc.handle_message("hvv_display/station/set", "Schlump")
    pc.handle_message("hvv_display/settings", json.dumps({"station": "Barmbek"}))
    assert pc.values()["station"] == "Schlump"


# -- commands from Home Assistant -----------------------------------------------------

def test_valid_command_is_stored_published_and_sent_to_the_program():
    pc, rec = make()
    restored(pc)
    channel = FakeChannel()
    pc.attach(channel)
    assert pc.handle_message("hvv_display/display/set", "Oberirdisch")
    assert rec.last("hvv_display/display/state") == "Oberirdisch"
    assert json.loads(rec.last("hvv_display/settings"))["display"] == "Oberirdisch"
    assert channel.sent[-1] == {"type": "set", "key": "display", "value": "Oberirdisch"}


def test_switch_and_number_payloads_are_converted():
    pc, _ = make()
    restored(pc)
    pc.handle_message("hvv_display/announcements/set", "OFF")
    pc.handle_message("hvv_display/rows/set", "3")
    assert pc.values()["announcements"] is False
    assert pc.values()["rows"] == 3


@pytest.mark.parametrize("key, payload", [
    ("display", "Kaputt"), ("rows", "9"), ("rows", "drei"), ("station", "x" * 81),
    ("station", "a\nb"), ("announcements", "maybe"),
])
def test_invalid_command_is_dropped_and_ha_snaps_back(key, payload):
    pc, rec = make()
    restored(pc)
    before = pc.values()[key]
    rec.published.clear()
    assert pc.handle_message(f"hvv_display/{key}/set", payload)
    assert pc.values()[key] == before
    assert rec.published == [(f"hvv_display/{key}/state",
                              pc.manifest.control(key).to_payload(before), True)]


def test_settings_can_change_while_the_program_is_not_running():
    pc, rec = make()
    restored(pc)
    pc.handle_message("hvv_display/station/set", "Schlump")
    channel = FakeChannel()
    pc.attach(channel)
    assert channel.sent[0] == {"type": "settings", "values": pc.values()}
    assert channel.sent[0]["values"]["station"] == "Schlump"


def test_button_press_only_reaches_a_running_program():
    pc, _ = make()
    restored(pc)
    assert pc.handle_message("hvv_display/refresh/set", "PRESS")  # nothing to send to
    channel = FakeChannel()
    pc.attach(channel)
    pc.handle_message("hvv_display/refresh/set", "PRESS")
    assert channel.sent[-1] == {"type": "press", "key": "refresh"}


def test_unrelated_topics_are_not_claimed():
    pc, _ = make()
    assert not pc.handle_message("display/control/start", "{}")
    assert not pc.handle_message("hvv_display/nope/set", "x")


# -- the running program ---------------------------------------------------------------

def test_attach_and_detach_drive_availability():
    pc, rec = make()
    restored(pc)
    channel = FakeChannel()
    pc.attach(channel)
    assert rec.last("hvv_display/availability") == "online"
    pc.detach()
    assert rec.last("hvv_display/availability") == "offline"
    assert channel.closed


def test_program_state_publishes_sensors_and_adopts_changed_controls():
    pc, rec = make()
    restored(pc)
    channel = FakeChannel()
    pc.attach(channel)
    channel.on_message({"type": "state", "values": {
        "station_name": "Barmbek (U3)", "station": "Barmbek U", "favorite": "Barmbek", "bogus": 1}})
    assert rec.last("hvv_display/station_name/state") == "Barmbek (U3)"
    assert rec.last("hvv_display/station/state") == "Barmbek U"
    assert pc.values()["favorite"] == "Barmbek"
    # The program's own change is not echoed back to it.
    assert all(m["type"] == "settings" for m in channel.sent)


def test_unchanged_sensor_values_are_not_republished():
    pc, rec = make()
    restored(pc)
    channel = FakeChannel()
    pc.attach(channel)
    channel.on_message({"type": "state", "values": {"station_name": "Barmbek"}})
    count = len(rec.published)
    channel.on_message({"type": "state", "values": {"station_name": "Barmbek"}})
    assert len(rec.published) == count


def test_presets_are_validated_and_applied():
    pc, rec = make()
    restored(pc)
    pc.apply_preset({"station": "Jungfernstieg", "display": "Oberirdisch"})
    assert rec.last("hvv_display/station/state") == "Jungfernstieg"
    with pytest.raises(ValueError):
        pc.apply_preset({"display": "Kaputt"})
    with pytest.raises(ValueError):
        pc.apply_preset({"nope": "x"})


def test_values_restored_after_launch_are_handed_to_the_program():
    pc, _ = make()
    pc.on_connect(now=0.0)
    channel = FakeChannel()
    pc.attach(channel)  # started before the snapshot arrived
    pc.handle_message("hvv_display/settings", json.dumps({"station": "Schlump"}))
    assert channel.sent[-1] == {"type": "settings", "values": pc.values()}
    assert channel.sent[-1]["values"]["station"] == "Schlump"


# -- the real channel, through a real child process ---------------------------------------

CHILD = r"""
import sys, time
sys.path.insert(0, {root!r})
from led_controller.program_client import ProgramClient
seen = {{}}
def on_settings(values):
    seen.update(values)
    client.send_state({{"station_name": "got " + values["station"]}})
def on_set(key, value):
    client.send_state({{"station_name": "set " + str(value), "station": "Normalised"}})
client = ProgramClient(on_settings=on_settings, on_set=on_set)
assert client.active
client.start()
time.sleep(3)
"""


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_round_trip_through_a_real_program(tmp_path):
    from pathlib import Path

    root = str(Path(__file__).resolve().parent.parent)
    script = tmp_path / "child.py"
    script.write_text(CHILD.format(root=root))
    pc, rec = make()
    restored(pc)
    channel = ControlChannel()
    handle = ProcessManager().launch(f"{sys.executable} {script}", channel=channel)
    try:
        pc.attach(channel)
        assert wait_for(lambda: rec.last("hvv_display/station_name/state") == "got Barmbek")
        pc.handle_message("hvv_display/display/set", "Oberirdisch")
        assert wait_for(lambda: rec.last("hvv_display/station_name/state") == "set Oberirdisch")
        assert wait_for(lambda: pc.values()["station"] == "Normalised")
    finally:
        pc.detach()
        ProcessManager().terminate(handle, 1.0)


def test_program_without_the_hub_has_an_inactive_client(monkeypatch):
    from led_controller.program_client import ProgramClient

    monkeypatch.delenv("LED_PANEL_CONTROL_FD", raising=False)
    client = ProgramClient()
    assert not client.active
    client.start()
    client.send_state({"x": 1})  # no-op, no error


# -- wired into the transition manager ---------------------------------------------------

def test_transition_manager_presets_attaches_and_detaches():
    from led_controller.commands import State
    from led_controller.relay import MockRelay
    from led_controller.state_machine import StateMachine
    from led_controller.transition_manager import TransitionManager
    from tests.test_transition_manager import RecordingProcessManager

    program = Program(
        id="hvv", name="HVV", command="hvv",
        subprograms={"schlump": Subprogram(id="schlump", name="Schlump",
                                           settings={"station": "Schlump"}),
                     "broken": Subprogram(id="broken", name="Broken",
                                          settings={"display": "Kaputt"})},
        manifest="hvv --manifest",
    )
    config = AppConfig(programs={"hvv": program}, system=SystemConfig(idle="idle", shutdown="bye"),
                       relay=RelayConfig())
    pc, rec = make()
    restored(pc)
    proc = RecordingProcessManager()
    tm = TransitionManager(config, StateMachine(initial=State.IDLE), proc, MockRelay(),
                           ControlsHub({"hvv": pc}))

    tm.start("hvv", "Schlump")
    assert pc.values()["station"] == "Schlump"
    assert isinstance(proc.channels[-1], ControlChannel)
    assert pc.running
    tm.stop()
    assert not pc.running
    assert proc.channels[-1] is None  # the idle animation gets no channel

    tm.start("hvv", "broken")
    assert tm.last_error is not None and "Kaputt" in tm.last_error.message

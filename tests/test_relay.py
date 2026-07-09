from __future__ import annotations

from led_controller.relay import MockRelay, build_relay


def test_mock_relay_starts_off():
    relay = MockRelay()
    assert relay.is_on is False


def test_mock_relay_on_off():
    relay = MockRelay()
    relay.on()
    assert relay.is_on is True
    relay.off()
    assert relay.is_on is False


def test_build_relay_mock_backend():
    relay = build_relay("mock", pin=26)
    assert isinstance(relay, MockRelay)


def test_gpiozero_relay_with_mock_pin_factory():
    from gpiozero import Device
    from gpiozero.pins.mock import MockFactory

    Device.pin_factory = MockFactory()
    try:
        relay = build_relay("gpio", pin=26)
        assert relay.is_on is False
        relay.on()
        assert relay.is_on is True
        relay.off()
        assert relay.is_on is False
    finally:
        Device.pin_factory = None

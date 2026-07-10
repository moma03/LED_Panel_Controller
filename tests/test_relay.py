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


def test_gpiozero_relay_active_low_starts_off_and_drives_pin_high():
    # Active-low boards energize on a LOW signal, so a correctly-off relay must
    # leave the underlying GPIO pin HIGH -- this is exactly the polarity bug
    # bug 1 was about: without active_low support, off() drove the pin LOW, which
    # energized an active-low relay board immediately at startup.
    from gpiozero import Device
    from gpiozero.pins.mock import MockFactory

    Device.pin_factory = MockFactory()
    try:
        relay = build_relay("gpio", pin=26, active_low=True)
        assert relay.is_on is False
        assert relay._device.pin.state == 1  # physical pin HIGH == relay off
        relay.on()
        assert relay.is_on is True
        assert relay._device.pin.state == 0  # physical pin LOW == relay energized
    finally:
        Device.pin_factory = None

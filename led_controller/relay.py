"""Display PSU relay control.

RelayController is a plain Protocol so the hardware backend is swappable
without touching any other module: GPIOZeroRelay drives a real pin on the
Pi, MockRelay is an in-memory stand-in for dev machines and tests.
"""

from __future__ import annotations

from typing import Protocol


class RelayController(Protocol):
    def on(self) -> None: ...
    def off(self) -> None: ...
    @property
    def is_on(self) -> bool: ...


class MockRelay:
    """In-memory relay for development off the Pi and for unit tests."""

    def __init__(self) -> None:
        self._on = False

    def on(self) -> None:
        self._on = True

    def off(self) -> None:
        self._on = False

    @property
    def is_on(self) -> bool:
        return self._on


class GPIOZeroRelay:
    """Drives a real GPIO pin via gpiozero. Only import gpiozero when actually used,
    so the mock path works on machines without RPi GPIO support at all.

    Many cheap relay boards are active-low (a LOW signal energizes the relay), so
    driving the pin to its logical "off" level at construction time -- before any
    Power On command has been received -- switches the PSU on immediately instead
    of leaving it off. `active_low` lets gpiozero translate on()/off()/is_on to the
    correct physical level for the board actually wired up, so `is_on` stays an
    honest match for what's connected to the PSU regardless of polarity."""

    def __init__(self, pin: int, active_low: bool = False):
        from gpiozero import DigitalOutputDevice

        self._device = DigitalOutputDevice(pin, active_high=not active_low, initial_value=False)

    def on(self) -> None:
        self._device.off()

    def off(self) -> None:
        self._device.on()

    @property
    def is_on(self) -> bool:
        return bool(self._device.value)


def build_relay(backend: str, pin: int, active_low: bool = False) -> RelayController:
    if backend == "gpio":
        return GPIOZeroRelay(pin, active_low)
    return MockRelay()

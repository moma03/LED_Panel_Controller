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
    so the mock path works on machines without RPi GPIO support at all."""

    def __init__(self, pin: int):
        from gpiozero import DigitalOutputDevice

        self._device = DigitalOutputDevice(pin, initial_value=False)

    def on(self) -> None:
        self._device.on()

    def off(self) -> None:
        self._device.off()

    @property
    def is_on(self) -> bool:
        return bool(self._device.value)


def build_relay(backend: str, pin: int) -> RelayController:
    if backend == "gpio":
        return GPIOZeroRelay(pin)
    return MockRelay()

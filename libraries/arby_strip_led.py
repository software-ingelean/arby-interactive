"""Nonblocking adapter for the plant's existing NeoPixel test script."""
from dataclasses import dataclass
import math
import time

from .control_tira_led import expansion


@dataclass(frozen=True)
class StripConfig:
    gpio: int = 12
    led_count: int = 55
    brightness: float = 0.20
    response_effect: str = "solid"

    def __post_init__(self):
        if self.gpio < 0 or self.led_count < 1 or not 0 <= self.brightness <= 1:
            raise ValueError("Invalid strip pin, length or brightness")
        if self.response_effect not in {"solid", "breathing", "bounce", "center_out", "ripple"}:
            raise ValueError("Unknown strip effect")


class LedStripController:
    """Call set_visual/update/close from the hardware/render thread only."""

    def __init__(self, config=None, *, pixels=None):
        self.config = config or StripConfig()
        if pixels is None:
            import board
            import neopixel
            pin = getattr(board, f"D{self.config.gpio}", None)
            if pin is None:
                raise ValueError(f"GPIO{self.config.gpio} is unavailable in board")
            pixels = neopixel.NeoPixel(
                pin, self.config.led_count, brightness=self.config.brightness,
                auto_write=False, pixel_order=neopixel.GRB,
            )
        self.pixels = pixels
        self._closed = False
        self._color = (40, 215, 255)
        self._phase = "idle"
        self._signature = None
        self._started = time.monotonic()
        try:
            # Initialize NeoPixel hardware before RGBMatrix can drop privileges.
            self.pixels.brightness = self.config.brightness
            self.pixels.fill((0, 0, 0))
            self.pixels.show()
        except Exception:
            self.pixels.deinit()
            raise

    def set_visual(self, color, phase, *, now=None):
        color = tuple(color)
        if len(color) != 3 or any(type(c) is not int or not 0 <= c <= 255 for c in color):
            raise ValueError("RGB channels must be integers from 0 to 255")
        if phase not in {"idle", "loading", "speaking"}:
            raise ValueError("Unknown application phase")
        signature = (color, phase)
        if signature != self._signature:
            self._color, self._phase = color, phase
            self._signature = signature
            self._started = time.monotonic() if now is None else now

    def update(self, now=None):
        if self._closed:
            return
        now = time.monotonic() if now is None else now
        elapsed = max(0, now - self._started)
        effect = {"idle": "breathing", "loading": "bounce"}.get(
            self._phase, self.config.response_effect)
        color = self._color
        step = int(elapsed / 0.04)
        if effect == "solid":
            self.pixels.fill(color)
        elif effect == "breathing":
            factor = 0.2 + 0.8 * (1 - math.cos(elapsed * math.pi)) / 2
            self.pixels.fill(tuple(round(c * factor) for c in color))
        elif effect == "bounce":
            self.pixels.fill((0, 0, 0))
            span = max(1, 2 * (len(self.pixels) - 1))
            position = step % span
            if position >= len(self.pixels):
                position = span - position
            for i in range(len(self.pixels)):
                factor = max(0, 1 - abs(i - position) / 5)
                self.pixels[i] = tuple(round(c * factor) for c in color)
        else:
            expansion(self.pixels, step, color, estela=5 if effect == "ripple" else 0)
        self.pixels.show()

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.pixels.fill((0, 0, 0))
            self.pixels.show()
        finally:
            self.pixels.deinit()

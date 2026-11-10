"""In-memory LED strip for running Arby without GPIO hardware."""


class MemoryPixels:
    """Same update path as physical LEDs, without importing GPIO packages."""

    def __init__(self, count):
        self.values = [(0, 0, 0)] * count
        self.brightness = 0.2

    def __len__(self):
        return len(self.values)

    def __setitem__(self, index, color):
        self.values[index] = color

    def fill(self, color):
        self.values[:] = [color] * len(self.values)

    def show(self):
        pass

    def deinit(self):
        pass

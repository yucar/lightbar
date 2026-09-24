"""Host stand-in for Pimoroni's `plasma` module: records set_hsv calls."""


class WS2812:
    def __init__(self, num_leds, *args, **kwargs):
        self.pixels = [(0.0, 0.0, 0.0)] * num_leds

    def start(self, fps=60):
        pass

    def set_hsv(self, i, h, s=1.0, v=1.0):
        self.pixels[i] = (h, s, v)

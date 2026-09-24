"""Host stand-in for Pimoroni's `pimoroni` module."""


class RGBLED:
    def __init__(self, *pins):
        self.rgb = (0, 0, 0)

    def set_rgb(self, r, g, b):
        self.rgb = (r, g, b)

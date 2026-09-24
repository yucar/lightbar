"""Host stand-in for MicroPython's `machine` module."""


class Pin:
    IN = 0
    PULL_UP = 1

    def __init__(self, *args, **kwargs):
        self._value = 1                     # button released (active low)

    def value(self, v=None):
        if v is None:
            return self._value
        self._value = v


def unique_id():
    return b"\xe6\x61\x41\x04\xa1\xb2\xc3"

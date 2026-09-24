"""Host stand-in for MicroPython's `network` module: always connected."""

STA_IF = 0


def hostname(name=None):
    return "lightbar"


class WLAN:
    def __init__(self, interface):
        pass

    def active(self, on=None):
        return True

    def config(self, **kwargs):
        pass

    def ifconfig(self, cfg=None):
        return ("127.0.0.1", "255.0.0.0", "127.0.0.1", "127.0.0.1")

    def isconnected(self):
        return True

    def connect(self, ssid, password):
        pass

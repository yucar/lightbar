"""Make the MicroPython firmware importable under CPython for tests.

Adds the firmware and shim directories to sys.path and provides the
MicroPython-only time.ticks_ms / time.ticks_diff functions.
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FIRMWARE = os.path.join(os.path.dirname(HERE), "plasma2350w")

for path in (os.path.join(HERE, "shims"), FIRMWARE):
    if path not in sys.path:
        sys.path.insert(0, path)

if not hasattr(time, "ticks_ms"):
    time.ticks_ms = lambda: int(time.monotonic() * 1000)
    time.ticks_diff = lambda a, b: a - b

"""Button state machine and a full-firmware smoke test."""

import asyncio
import shutil
import subprocess
import tempfile
import time
import types
import unittest

import host  # noqa: F401

import app
import config
import plasma
from lightbar import Lightbar
from test_network import free_port


class FakePin:
    def __init__(self):
        self.down = False

    def value(self):
        return 0 if self.down else 1


class ButtonTest(unittest.TestCase):
    def setUp(self):
        self.bar = Lightbar(plasma.WS2812(config.NUM_LEDS), config)
        self.pin = FakePin()
        self.button = app.Button(self.pin, self.bar)

    def hold_for(self, ms):
        self.pin.down = True
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            self.button.poll()
            time.sleep(0.005)

    def release(self):
        self.pin.down = False
        for _ in range(10):
            self.button.poll()
            time.sleep(0.005)

    def click(self):
        self.hold_for(60)
        self.release()

    def test_click_on_then_quick_click_randomizes_then_click_off(self):
        self.click()
        self.assertTrue(self.bar.any_on())
        hues = [l.hue for l in self.bar.lights]
        self.click()                                    # within 2 s → randomize
        self.assertTrue(self.bar.any_on())
        self.assertNotEqual(hues, [l.hue for l in self.bar.lights])
        self.button._last_on -= 5000                    # pretend 5 s passed
        self.click()
        self.assertFalse(self.bar.any_on())

    def test_bounce_is_ignored(self):
        self.pin.down = True
        self.button.poll()                              # 1 ms glitch
        self.pin.down = False
        for _ in range(10):
            self.button.poll()
            time.sleep(0.005)
        self.assertFalse(self.bar.any_on())

    def test_hold_from_off_brightens_then_next_hold_dims(self):
        self.hold_for(1200)
        self.release()
        self.assertTrue(self.bar.any_on())
        up = self.bar.master_brightness()
        self.assertGreater(up, config.MIN_BRIGHTNESS)
        self.assertLess(up, 1.0)
        self.hold_for(900)
        self.release()
        self.assertLess(self.bar.master_brightness(), up)
        self.assertTrue(self.bar.any_on(), "releasing a hold must not toggle")


@unittest.skipUnless(shutil.which("mosquitto"), "mosquitto not installed")
class AppSmokeTest(unittest.IsolatedAsyncioTestCase):
    async def test_boots_connects_and_serves(self):
        port = free_port()
        with tempfile.TemporaryDirectory() as tmp:
            conf = tmp + "/m.conf"
            with open(conf, "w") as f:
                f.write("listener {} 127.0.0.1\nallow_anonymous true\n".format(port))
            broker = subprocess.Popen(["mosquitto", "-c", conf],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            old = (config.MQTT_HOST, config.MQTT_PORT, config.HTTP_PORT)
            config.MQTT_HOST, config.MQTT_PORT, config.HTTP_PORT = "127.0.0.1", port, 0
            try:
                await asyncio.sleep(0.3)
                secrets = types.SimpleNamespace(WIFI_SSID="x", WIFI_PASSWORD="y",
                                                API_TOKEN="t")
                application = app.App(secrets)
                task = asyncio.create_task(application.run())
                for _ in range(40):
                    if application.mqtt.connected:
                        break
                    await asyncio.sleep(0.1)
                self.assertTrue(application.mqtt.connected)
                await asyncio.sleep(0.25)               # status LED refreshes every 0.1 s
                self.assertEqual(application.device_id, "lightbar_a1b2c3")
                self.assertEqual(application.status_led.rgb, (0, 3, 0))
                task.cancel()
                await application.mqtt._close()
            finally:
                config.MQTT_HOST, config.MQTT_PORT, config.HTTP_PORT = old
                broker.terminate()
                broker.wait()


if __name__ == "__main__":
    unittest.main()

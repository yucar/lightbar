"""REST API and MQTT / Home Assistant discovery, over real sockets.

The MQTT tests start a throw-away Mosquitto broker and use the
`mosquitto_sub` / `mosquitto_pub` CLI as an independent "Home Assistant".
They are skipped when Mosquitto is not installed.
"""

import asyncio
import json
import shutil
import socket
import subprocess
import tempfile
import unittest

import host  # noqa: F401

import config
import plasma
from ha import HomeAssistant
from http_api import RestApi
from lightbar import Lightbar
from mqtt import MQTTClient

TOKEN = "s3cret"


async def http(port, method, path, body=None, token=TOKEN):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    head = "{} {} HTTP/1.1\r\nHost: x\r\n".format(method, path)
    if token:
        head += "Authorization: Bearer {}\r\n".format(token)
    data = json.dumps(body).encode() if body is not None else b""
    head += "Content-Length: {}\r\n\r\n".format(len(data))
    writer.write(head.encode() + data)
    await writer.drain()
    raw = await reader.read()
    writer.close()
    status = int(raw.split(b" ")[1])
    return status, json.loads(raw.split(b"\r\n\r\n", 1)[1])


class RestApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bar = Lightbar(plasma.WS2812(config.NUM_LEDS), config)
        self.api = RestApi(self.bar, TOKEN, info={"firmware": "test"})
        await self.api.start(0)
        self.port = self.api._server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.api._server.close()

    async def test_requires_token(self):
        status, _ = await http(self.port, "GET", "/status", token=None)
        self.assertEqual(status, 401)
        status, _ = await http(self.port, "GET", "/status", token="wrong")
        self.assertEqual(status, 401)

    async def test_get_cannot_change_state(self):
        status, _ = await http(self.port, "GET", "/on")
        self.assertEqual(status, 405)
        self.assertFalse(self.bar.any_on())

    async def test_per_light_brightness(self):
        status, state = await http(self.port, "POST", "/brightness?light=1&value=25")
        self.assertEqual(status, 200)
        self.assertAlmostEqual(state["lights"][1]["brightness"], 0.25)
        self.assertAlmostEqual(state["lights"][0]["brightness"], 1.0)

    async def test_one_percent_is_one_percent(self):
        _, state = await http(self.port, "POST", "/brightness?light=0&value=1")
        self.assertAlmostEqual(state["lights"][0]["brightness"], 0.01)

    async def test_on_single_light_and_json_body(self):
        _, state = await http(self.port, "POST", "/on", {"light": 1})
        self.assertEqual([l["on"] for l in state["lights"]], [False, True])

    async def test_color_rgb_and_hs(self):
        _, state = await http(self.port, "POST", "/color?light=0&r=0&g=0&b=255")
        self.assertAlmostEqual(state["lights"][0]["hue"], 2 / 3, places=3)
        _, state = await http(self.port, "POST", "/color?idx=1&h=90&s=50")
        self.assertAlmostEqual(state["lights"][1]["hue"], 0.25)
        self.assertAlmostEqual(state["lights"][1]["sat"], 0.5)

    async def test_bad_input_is_400(self):
        for path in ("/brightness?value=abc", "/brightness?value=500",
                     "/color?h=10&s=10", "/on?light=7"):
            status, _ = await http(self.port, "POST", path)
            self.assertEqual(status, 400, path)
        status, _ = await http(self.port, "GET", "/nope")
        self.assertEqual(status, 404)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(shutil.which("mosquitto"), "mosquitto not installed")
class HomeAssistantMqttTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.port = free_port()
        self.tmp = tempfile.TemporaryDirectory()
        conf = "{}/mosquitto.conf".format(self.tmp.name)
        with open(conf, "w") as f:
            f.write("listener {} 127.0.0.1\nallow_anonymous true\n".format(self.port))
        self.broker = subprocess.Popen(["mosquitto", "-c", conf],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        await asyncio.sleep(0.3)

        self.bar = Lightbar(plasma.WS2812(config.NUM_LEDS), config)
        self.client = MQTTClient("lightbar_test", "127.0.0.1", self.port, keepalive=5)
        self.ha = HomeAssistant(self.bar, self.client, config, "lightbar_test")
        self.changed = asyncio.Event()
        self.bar.on_change = self.changed.set
        self.online = True                  # simulated WiFi
        self.tasks = [asyncio.create_task(self.client.run(can_connect=lambda: self.online)),
                      asyncio.create_task(self._sync())]
        for _ in range(50):
            if self.client.connected:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.3)

    async def _sync(self):
        while True:
            await self.changed.wait()
            await asyncio.sleep(0.05)
            self.changed.clear()
            await self.ha.publish_state()

    async def asyncTearDown(self):
        for t in self.tasks:
            t.cancel()
        await self.client._close()
        self.broker.terminate()
        self.broker.wait()
        self.tmp.cleanup()

    def retained(self, topic):
        """Read retained messages like HA does after a restart."""
        out = subprocess.run(
            ["mosquitto_sub", "-p", str(self.port), "-t", topic, "-v", "-W", "1"],
            capture_output=True, text=True).stdout
        msgs = {}
        for line in out.splitlines():
            t, _, payload = line.partition(" ")
            msgs[t] = payload
        return msgs

    def pub(self, topic, payload):
        subprocess.run(["mosquitto_pub", "-p", str(self.port), "-t", topic, "-m", payload],
                       check=True)

    async def test_discovery_is_retained(self):
        found = await asyncio.to_thread(self.retained, "homeassistant/#")
        self.assertEqual(sorted(found), [
            "homeassistant/button/lightbar_test/randomize/config",
            "homeassistant/light/lightbar_test/all/config",
            "homeassistant/light/lightbar_test/light0/config",
            "homeassistant/light/lightbar_test/light1/config",
        ])
        light1 = json.loads(found["homeassistant/light/lightbar_test/light1/config"])
        self.assertEqual(light1["name"], "End")
        self.assertEqual(light1["schema"], "json")
        self.assertEqual(light1["supported_color_modes"], ["hs"])
        self.assertIsNone(json.loads(found["homeassistant/light/lightbar_test/all/config"])["name"])
        avail = await asyncio.to_thread(self.retained, "lightbar/lightbar_test/availability")
        self.assertEqual(list(avail.values()), ["online"])

    async def test_command_sets_individual_light_and_echoes_state(self):
        await asyncio.to_thread(self.pub, "lightbar/lightbar_test/light/1/set",
                                '{"state":"ON","brightness":64,"color":{"h":120,"s":50}}')
        await asyncio.sleep(0.4)
        light = self.bar.lights[1]
        self.assertTrue(light.on)
        self.assertFalse(self.bar.lights[0].on)
        self.assertAlmostEqual(light.brightness, 64 / 255, places=3)
        self.assertAlmostEqual(light.hue, 1 / 3, places=3)
        states = await asyncio.to_thread(self.retained, "lightbar/lightbar_test/+/+/state")
        state = json.loads(states["lightbar/lightbar_test/light/1/state"])
        self.assertEqual(state, {"state": "ON", "brightness": 64, "color_mode": "hs",
                                 "color": {"h": 120.0, "s": 50.0}})

    async def test_local_changes_are_reported(self):
        self.bar.set_all(on=True)            # e.g. the physical button
        await asyncio.sleep(0.3)
        states = await asyncio.to_thread(self.retained, "lightbar/lightbar_test/all/state")
        self.assertEqual(json.loads(states["lightbar/lightbar_test/all/state"])["state"], "ON")

    async def test_all_light_brightness_scales_both(self):
        self.bar.set_light(0, on=True, brightness=1.0)
        self.bar.set_light(1, on=True, brightness=0.5)
        await asyncio.to_thread(self.pub, "lightbar/lightbar_test/all/set",
                                '{"state":"ON","brightness":51}')
        await asyncio.sleep(0.3)
        self.assertAlmostEqual(self.bar.lights[0].brightness, 0.2, places=3)
        self.assertAlmostEqual(self.bar.lights[1].brightness, 0.1, places=3)

    async def test_garbage_does_not_break_the_link(self):
        await asyncio.to_thread(self.pub, "lightbar/lightbar_test/light/0/set", "not json")
        await asyncio.to_thread(self.pub, "lightbar/lightbar_test/light/9/set", '{"state":"ON"}')
        await asyncio.to_thread(self.pub, "lightbar/lightbar_test/light/0/set",
                                '{"state":"ON","transition":"x"}')
        await asyncio.to_thread(self.pub, "lightbar/lightbar_test/randomize", "PRESS")
        await asyncio.sleep(0.3)
        self.assertTrue(self.client.connected)
        self.assertEqual(self.bar.lights[0].sat, 1.0)          # randomize ran

    async def test_last_will_marks_offline_then_recovers(self):
        self.online = False
        self.client._writer.transport.abort()   # simulate power loss / WiFi drop
        await asyncio.sleep(0.5)
        avail = await asyncio.to_thread(self.retained, "lightbar/lightbar_test/availability")
        self.assertEqual(list(avail.values()), ["offline"])
        self.online = True
        for _ in range(100):
            if self.client.connected:
                break
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.2)
        avail = await asyncio.to_thread(self.retained, "lightbar/lightbar_test/availability")
        self.assertEqual(list(avail.values()), ["online"])

if __name__ == "__main__":
    unittest.main()

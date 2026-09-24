"""Gradient math and light state (no network)."""

import os
import tempfile
import time
import unittest

import host  # noqa: F401 — sets up sys.path and ticks_ms

import config
import gradient
import plasma
from lightbar import Lightbar


def frame_led(frame, i):
    return tuple(round(x, 4) for x in frame[i * 3:i * 3 + 3])


def settle(bar):
    """Run the renderer until the current fade has finished."""
    deadline = time.monotonic() + 5
    while bar._animating and time.monotonic() < deadline:
        bar.tick()
        time.sleep(0.01)


class GradientTest(unittest.TestCase):
    def test_endpoints_hit_the_anchors(self):
        out = gradient.new_frame(10)
        gradient.build(out, 10, [(0.1, 1.0, 0.2), (0.3, 0.5, 1.0)])
        self.assertEqual(frame_led(out, 0), (0.1, 1.0, 0.2))
        self.assertEqual(frame_led(out, 9), (0.3, 0.5, 1.0))

    def test_brightness_blends_linearly_between_lights(self):
        out = gradient.new_frame(5)
        gradient.build(out, 5, [(0.0, 1.0, 0.0), (0.0, 1.0, 1.0)])
        self.assertEqual([round(out[i * 3 + 2], 2) for i in range(5)],
                         [0.0, 0.25, 0.5, 0.75, 1.0])

    def test_hue_travels_forward(self):
        out = gradient.new_frame(3)
        gradient.build(out, 3, [(0.9, 1.0, 1.0), (0.1, 1.0, 1.0)])
        self.assertAlmostEqual(out[3], 0.0, places=4)      # 0.9 → 1.0/0.0 → 0.1

    def test_same_hue_is_solid(self):
        out = gradient.new_frame(4)
        gradient.build(out, 4, [(0.5, 1.0, 1.0), (0.5, 1.0, 1.0)])
        self.assertTrue(all(abs(out[i * 3] - 0.5) < 1e-6 for i in range(4)))

    def test_three_anchors(self):
        out = gradient.new_frame(5)
        gradient.build(out, 5, [(0.0, 1, 1), (0.2, 1, 0.5), (0.4, 1, 1)])
        self.assertEqual(frame_led(out, 2), (0.2, 1.0, 0.5))

    def test_blend_takes_short_hue_path(self):
        a, b, out = gradient.new_frame(1), gradient.new_frame(1), gradient.new_frame(1)
        a[0], b[0] = 0.95, 0.05
        gradient.blend(out, a, b, 0.5, 1)
        self.assertAlmostEqual(out[0] % 1.0, 0.0, places=4)


class LightbarTest(unittest.TestCase):
    def setUp(self):
        self.strip = plasma.WS2812(config.NUM_LEDS)
        self.bar = Lightbar(self.strip, config)
        self.changes = 0
        self.bar.on_change = self._count

    def _count(self):
        self.changes += 1

    def test_individual_brightness_and_smooth_blend(self):
        self.bar.set_light(0, on=True, brightness=1.0, transition=0)
        self.bar.set_light(1, on=True, brightness=0.2, transition=0)
        settle(self.bar)
        first = self.strip.pixels[0][2]
        middle = self.strip.pixels[config.NUM_LEDS // 2][2]
        last = self.strip.pixels[-1][2]
        self.assertAlmostEqual(first, 1.0, places=3)
        self.assertAlmostEqual(last, 0.2, places=3)
        self.assertTrue(last < middle < first)

    def test_one_light_off_fades_that_end_only(self):
        self.bar.set_all(on=True, transition=0)
        self.bar.set_light(1, on=False, transition=0)
        settle(self.bar)
        self.assertGreater(self.strip.pixels[0][2], 0.9)
        self.assertEqual(self.strip.pixels[-1][2], 0.0)
        self.assertTrue(self.bar.any_on())

    def test_all_brightness_keeps_ratios(self):
        self.bar.set_light(0, on=True, brightness=0.8)
        self.bar.set_light(1, on=True, brightness=0.4)
        self.bar.set_all(brightness=0.4)
        self.assertAlmostEqual(self.bar.lights[0].brightness, 0.4)
        self.assertAlmostEqual(self.bar.lights[1].brightness, 0.2)

    def test_fade_is_gradual(self):
        self.bar.set_all(on=True, transition=0.3)
        self.bar.tick()
        time.sleep(0.15)
        self.bar.tick()
        mid = self.strip.pixels[0][2]
        self.assertTrue(0.0 < mid < 1.0, mid)
        settle(self.bar)
        self.assertAlmostEqual(self.strip.pixels[0][2], 1.0, places=3)

    def test_retarget_mid_fade_is_continuous(self):
        self.bar.set_all(on=True, transition=0.4)
        time.sleep(0.2)
        self.bar.tick()
        before = self.strip.pixels[0][2]
        self.bar.set_all(on=False, transition=0.4)
        self.bar.tick()                     # first frame of the new fade
        self.assertAlmostEqual(self.strip.pixels[0][2], before, delta=0.05)

    def test_no_change_no_notification(self):
        self.bar.set_light(0, on=False)     # already off
        self.assertEqual(self.changes, 0)

    def test_save_and_restore(self):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                self.bar.set_light(1, on=True, brightness=0.3, hue=0.25, sat=0.5)
                self.bar.save()
                fresh = Lightbar(plasma.WS2812(config.NUM_LEDS), config)
                fresh.restore("restore")
                self.assertTrue(fresh.lights[1].on)
                self.assertAlmostEqual(fresh.lights[1].brightness, 0.3)
                self.assertAlmostEqual(fresh.lights[1].hue, 0.25)
                off = Lightbar(plasma.WS2812(config.NUM_LEDS), config)
                off.restore("off")
                self.assertFalse(off.any_on())
                self.assertAlmostEqual(off.lights[1].brightness, 0.3)
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()

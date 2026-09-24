# gradient.py — Polychromatic HSV gradient math for Lightbar
# Version: 2.0.0
#
# Builds a gradient across the strip from N evenly spaced anchors
# ("virtual lights"). Each anchor is (hue, saturation, value), all 0.0-1.0.
#
#   • Hue travels FORWARD around the colour wheel between anchors
#     (polychromatic / rainbow-like). Two anchors with the same hue give a
#     solid colour; a small backwards step gives an almost-full rainbow.
#   • Saturation and value are interpolated linearly, so each light's
#     brightness blends smoothly into its neighbour's.
#
# Frames are stored in flat float arrays: [h0, s0, v0, h1, s1, v1, ...].
# This avoids allocating 192 tuples per frame and keeps the GC quiet.

from array import array

try:
    from micropython import native
except ImportError:  # CPython (tests) or a build without the native emitter
    def native(f):
        return f


def new_frame(num_leds):
    """Allocate a zeroed frame buffer for num_leds LEDs."""
    return array("f", [0.0] * (num_leds * 3))


@native
def build(out, num_leds, anchors):
    """Fill `out` with a gradient through `anchors` (list of (h, s, v))."""
    n_anchors = len(anchors)
    if n_anchors == 1 or num_leds == 1:
        h, s, v = anchors[0]
        for i in range(num_leds):
            j = i * 3
            out[j] = h
            out[j + 1] = s
            out[j + 2] = v
        return

    segments = n_anchors - 1
    last = num_leds - 1
    for i in range(num_leds):
        # Position along the strip in "segments", e.g. 0.0 .. 2.0 for 3 anchors.
        pos = i * segments / last
        seg = int(pos)
        if seg >= segments:
            seg = segments - 1
        t = pos - seg
        h1, s1, v1 = anchors[seg]
        h2, s2, v2 = anchors[seg + 1]
        dh = (h2 - h1) % 1.0          # forward distance around the wheel
        j = i * 3
        out[j] = (h1 + dh * t) % 1.0
        out[j + 1] = s1 + (s2 - s1) * t
        out[j + 2] = v1 + (v2 - v1) * t


@native
def blend(out, a, b, t, num_leds):
    """out = a → b at fraction t, hue along the SHORTEST path.

    Used for crossfades between two frames so any change (colour,
    brightness, on/off) is continuous, even mid-transition.
    """
    for i in range(num_leds):
        j = i * 3
        h1 = a[j]
        dh = b[j] - h1
        if dh > 0.5:
            dh -= 1.0
        elif dh < -0.5:
            dh += 1.0
        out[j] = (h1 + dh * t) % 1.0
        out[j + 1] = a[j + 1] + (b[j + 1] - a[j + 1]) * t
        out[j + 2] = a[j + 2] + (b[j + 2] - a[j + 2]) * t

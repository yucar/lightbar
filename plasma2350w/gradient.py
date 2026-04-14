# gradient.py — Polychromatic HSV gradient math for Lightbar
# Version: 1.1.0
#
# Generates smooth HSV gradients across a WS2812 LED strip.
# Uses POLYCHROMATIC interpolation: hue always travels forward
# (increasing) around the color wheel, creating rainbow-like transitions.
# Supports 2-color and 3-color gradients.


def hsv_lerp_poly(h1, s1, v1, h2, s2, v2, t):
    """Polychromatic interpolation between two HSV colors.

    Hue ALWAYS travels forward (increasing) around the color wheel.
    """
    dh = h2 - h1
    if dh <= 0.0:
        dh += 1.0
    h = (h1 + dh * t) % 1.0
    s = s1 + (s2 - s1) * t
    v = v1 + (v2 - v1) * t
    return h, s, v


def hsv_lerp_short(h1, s1, v1, h2, s2, v2, t):
    """Shortest-path interpolation between two HSV colors."""
    dh = h2 - h1
    if dh > 0.5:
        dh -= 1.0
    elif dh < -0.5:
        dh += 1.0
    h = (h1 + dh * t) % 1.0
    s = s1 + (s2 - s1) * t
    v = v1 + (v2 - v1) * t
    return h, s, v


def gradient_2color(num_leds, h1, s1, v1, h2, s2, v2, polychromatic=True):
    """Generate a 2-color gradient across num_leds LEDs."""
    if num_leds <= 1:
        return [(h1, s1, v1)]
    lerp = hsv_lerp_poly if polychromatic else hsv_lerp_short
    result = []
    for i in range(num_leds):
        t = i / (num_leds - 1)
        result.append(lerp(h1, s1, v1, h2, s2, v2, t))
    return result


def gradient_3color(num_leds, h1, s1, v1, h2, s2, v2, h3, s3, v3,
                    polychromatic=True):
    """Generate a 3-color gradient across num_leds LEDs.
    Color 1 at start, color 2 in middle, color 3 at end.
    """
    if num_leds <= 1:
        return [(h1, s1, v1)]
    if num_leds == 2:
        return [(h1, s1, v1), (h3, s3, v3)]
    lerp = hsv_lerp_poly if polychromatic else hsv_lerp_short
    mid = num_leds // 2
    result = []
    for i in range(mid):
        t = i / mid
        result.append(lerp(h1, s1, v1, h2, s2, v2, t))
    remaining = num_leds - mid
    for i in range(remaining):
        t = i / (remaining - 1) if remaining > 1 else 1.0
        result.append(lerp(h2, s2, v2, h3, s3, v3, t))
    return result

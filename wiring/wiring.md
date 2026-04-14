# Lightbar — Wiring
<!-- Version: 2.0.0 -->

## Overview

The Plasma 2350 W is a **single-board** design. No secondary microcontroller
is needed. Everything connects directly to the Plasma's screw terminals.

```
                         USB-C (power + programming)
                               │
                    ┌──────────┴──────────┐
                    │  Pimoroni Plasma    │
                    │     2350 W          │
                    │                     │
                    │  RP2350 + CYW43439  │
                    │                     │
                    │  [DAT] [5V] [GND]   │
                    └──┬──────┬──────┬────┘
                       │      │      │
                    ┌──┘      │      └──┐
                    ▼         ▼         ▼
                   DIN       VCC       GND
              ┌────────────────────────────┐
              │   LED Strip 1 (96 LEDs)    │
              └────────────┬───────────────┘
                          DOUT
                           │
                          DIN
              ┌────────────────────────────┐
              │   LED Strip 2 (96 LEDs)    │
              └────────────────────────────┘
```

---

## LED Strips → Plasma 2350 W Screw Terminals

| Plasma terminal | Strip wire | Notes |
|---|---|---|
| **DAT** | DIN (data in) of strip 1 | PIO-driven WS2812 signal |
| **5V** | VCC / +5V of strip 1 | Powered from USB-C |
| **GND** | GND of strip 1 | Common ground |

Strip 1's **DOUT** (data out) connects to strip 2's **DIN** — they run in series as 192 LEDs total.

---

## Power

| Source | Powers | Max |
|---|---|---|
| **Plasma USB-C** | Plasma board + both LED strips | 3 A @ 5 V = 15 W |

For typical gradient use (not full white at max brightness), USB-C is sufficient
for 192 LEDs. The firmware status LED turns orange if WiFi drops, but there is
no overcurrent protection on the 2350 W — keep an eye on power draw if using
many LEDs at full white.

If you need more headroom, power the strips from an external 5V PSU directly
(connect GND to the Plasma's GND too).

---

## Status LED Reference

| Colour | Meaning |
|---|---|
| Blue pulse | Connecting to WiFi |
| Green | Connected, all OK |
| Orange | WiFi disconnected, retrying |

---

## Button Reference

| Button | Location | Use |
|---|---|---|
| **A** (USER) | Labelled "A" on the board — GP23 | Main user button |
| **BOOT** | Next to A | Enter bootloader (hold while tapping RESET) |
| **RESET** | End of board | Restart the firmware |

The firmware only uses **Button A** (GP23). BOOT is only needed for flashing.

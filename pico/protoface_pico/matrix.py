"""HUB75 panel bring-up via Protomatter (rgbmatrix + framebufferio).

On the RP2350 the panel is driven by CircuitPython's native ``rgbmatrix``
module (Adafruit Protomatter under the hood), which clocks HUB75 out over PIO +
DMA. ``framebufferio.FramebufferDisplay`` then refreshes the panel from a
``displayio`` group automatically, so the CPU is free for compositing.

Default pin mapping matches the **Pimoroni Interstate 75 / Interstate 75 W** —
a turnkey Pico-class RP2350 HUB75 driver board — so an Interstate 75 W works
out of the box. Wiring your own Pico 2 to a panel/bonnet? Override the pins in
config.json under ``panel.pins``.

For a 64-row panel set ``panel.panel_height: 64`` and add the 5th address pin
(``"e": "GP10"``) to ``panel.pins``.
"""

import board
import displayio
import framebufferio
import rgbmatrix

# Interstate 75 (W) pin names, as board attribute strings.
_DEFAULT_PINS = {
    "rgb": ["R0", "G0", "B0", "R1", "G1", "B1"],
    "addr": ["ROW_A", "ROW_B", "ROW_C", "ROW_D"],  # add "ROW_E" for 64-row
    "clock": "CLK",
    "latch": "LAT",
    "oe": "OE",
}

# Fallback to raw GP numbering if the friendly Interstate 75 names are absent
# (e.g. a bare Pico 2). These match the Interstate 75 GPIO assignments.
_GP_FALLBACK = {
    "rgb": ["GP0", "GP1", "GP2", "GP3", "GP4", "GP5"],
    "addr": ["GP6", "GP7", "GP8", "GP9"],
    "clock": "GP11",
    "latch": "GP12",
    "oe": "GP13",
}


def _pin(name):
    """Resolve a board pin by attribute name, raising a clear error if absent."""
    if not hasattr(board, name):
        raise ValueError(
            "board has no pin '%s' — set panel.pins in config.json for your wiring"
            % name
        )
    return getattr(board, name)


def _resolve_pins(cfg_pins):
    """Merge config pin overrides over the defaults and resolve to board pins."""
    spec = dict(_DEFAULT_PINS)
    # If the friendly names don't exist on this board, fall back to GP numbers.
    if not hasattr(board, spec["rgb"][0]):
        spec = dict(_GP_FALLBACK)
    spec.update(cfg_pins or {})

    return {
        "rgb_pins": [_pin(n) for n in spec["rgb"]],
        "addr_pins": [_pin(n) for n in spec["addr"]],
        "clock_pin": _pin(spec["clock"]),
        "latch_pin": _pin(spec["latch"]),
        "output_enable_pin": _pin(spec["oe"]),
    }


def build_display(cfg):
    """Create and return a FramebufferDisplay for the configured panel.

    Releases any previously-bound displays first so a soft reload re-inits
    cleanly.
    """
    panel = cfg["panel"]
    width = panel["panel_width"] * panel["chain_length"]
    height = panel["panel_height"]
    bit_depth = panel.get("bit_depth", 4)

    displayio.release_displays()

    pins = _resolve_pins(panel.get("pins"))
    matrix = rgbmatrix.RGBMatrix(
        width=width,
        height=height,
        bit_depth=bit_depth,
        rgb_pins=pins["rgb_pins"],
        addr_pins=pins["addr_pins"],
        clock_pin=pins["clock_pin"],
        latch_pin=pins["latch_pin"],
        output_enable_pin=pins["output_enable_pin"],
        doublebuffer=True,
    )
    return framebufferio.FramebufferDisplay(matrix, auto_refresh=True)

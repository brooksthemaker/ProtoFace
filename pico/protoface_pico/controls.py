"""Standalone controls for the Pico build.

Replaces the CM5 Unix-socket IPC + terminal KeyReader with local input. v1
reads single-key commands over the USB serial console (non-blocking), mirroring
the CM5 solo-mode keys:

    c / v   next / previous face colour
    x / z   next / previous particle effect
    e / w   next / previous expression
    b       manual blink
    + / -   brightness up / down

Physical buttons (e.g. the Interstate 75's A/B) can be wired in later via the
``keypad`` module; this serial layer keeps bring-up dependency-free.
"""

import sys

try:
    import supervisor
    _HAVE_SUPERVISOR = True
except ImportError:
    _HAVE_SUPERVISOR = False


def poll_key():
    """Return one pending serial char, or None. Never blocks."""
    if not _HAVE_SUPERVISOR:
        return None
    if supervisor.runtime.serial_bytes_available:
        ch = sys.stdin.read(1)
        return ch
    return None

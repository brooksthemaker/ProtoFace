"""
Non-blocking single-key terminal reader (POSIX). Safely no-ops when there is no
TTY (e.g. running under systemd), so it can be left in place unconditionally.

Usage:
    kb = KeyReader(); kb.start()
    ch = kb.get()        # returns one character, or None if nothing pending
    kb.stop()

or as a context manager:
    with KeyReader() as kb:
        ch = kb.get()
"""

import sys


class KeyReader:
    def __init__(self):
        self._ok = False
        self._fd = None
        self._old = None
        self._termios = None

    def start(self) -> "KeyReader":
        try:
            import termios, tty
            if not sys.stdin.isatty():
                return self
            self._termios = termios
            self._fd = sys.stdin.fileno()
            self._old = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)   # leaves ISIG on, so Ctrl-C still works
            self._ok = True
        except Exception:
            self._ok = False
        return self

    def get(self):
        """Return a single pending character, or None. Never blocks."""
        if not self._ok:
            return None
        import select
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1)
        return None

    def stop(self):
        if self._ok:
            try:
                self._termios.tcsetattr(self._fd, self._termios.TCSADRAIN, self._old)
            except Exception:
                pass
            self._ok = False

    def __enter__(self) -> "KeyReader":
        return self.start()

    def __exit__(self, *exc):
        self.stop()

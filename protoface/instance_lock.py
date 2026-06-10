"""
Single-instance guard shared by run.py and demo.py.

Two processes driving /dev/pio0 at once garble the panels with static, so
anything that owns the panels takes an exclusive flock on a well-known path
before starting.
"""

import sys

try:
    import fcntl              # POSIX file lock
except ImportError:
    fcntl = None


def acquire_instance_lock(path: str = '/tmp/protoface.lock'):
    """Hold an exclusive lock so a second Protoface can't start.

    Returns the lock file object — keep a reference for the process lifetime;
    the lock is released automatically when the process exits or is killed.
    Exits the process if another instance already holds the lock.
    """
    if fcntl is None:
        return None
    fd = open(path, 'w')
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"[protoface] already running (lock held on {path}) — exiting.")
        sys.exit(0)
    return fd

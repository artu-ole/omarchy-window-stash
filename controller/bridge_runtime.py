"""Serialize native replacement with acquisitions in this compositor session."""
import contextlib
import fcntl
import os
from pathlib import Path
import re


BUSY = 'Preview support is being reloaded; try again shortly'


@contextlib.contextmanager
def bridge_gate(exclusive=False):
    signature = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', '')
    runtime = os.environ.get('XDG_RUNTIME_DIR', '')
    if not signature or not runtime:
        raise RuntimeError('Run Window Stash inside a Hyprland session')
    directory = Path(runtime)/'omarchy-window-stash'/re.sub(r'[^A-Za-z0-9_-]', '_', signature)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(directory/'bridge.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a') as lock:
        try:
            fcntl.flock(lock, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(BUSY) from None
        yield

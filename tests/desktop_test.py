"""Announce desktop automation before it can take mouse or keyboard focus."""
from contextlib import contextmanager
import subprocess
import time


@contextmanager
def desktop_test(name):
    subprocess.run(['notify-send', '--app-name=Window Stash tests', '--expire-time=5000',
                    'Desktop test starts in 5 seconds',
                    name + ': please pause mouse and keyboard input until the completion notification.'],
                   check=True, timeout=5)
    for remaining in (5, 4, 3, 2, 1):
        print(f'{name}: desktop automation starts in {remaining}…', flush=True)
        time.sleep(1)
    failed = False
    try:
        yield
    except BaseException:
        failed = True
        raise
    finally:
        title = 'Desktop test ended with an error' if failed else 'Desktop test finished'
        print(f'{name}: desktop automation ended.', flush=True)
        try:
            subprocess.run(['notify-send', '--app-name=Window Stash tests', '--expire-time=5000',
                            title, name + ': you can use the mouse and keyboard again.'],
                           check=False, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass

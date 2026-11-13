#!/usr/bin/env python3
"""Raw owned terminal fixture; records only synthetic test input in /tmp."""
import json
import os
from pathlib import Path
import select
import signal
import sys
import termios
import tty

log = Path(sys.argv[1])
assert log.is_absolute() and log.resolve().is_relative_to('/tmp')


def emit(kind, **fields):
    with log.open('a') as output:
        output.write(json.dumps(dict(event=kind, **fields))+'\n')


def stop(_signal, _frame):
    raise SystemExit(0)


signal.signal(signal.SIGTERM, stop)
original = termios.tcgetattr(sys.stdin.fileno())
try:
    tty.setraw(sys.stdin.fileno())
    size = os.get_terminal_size()
    emit('ready', columns=size.columns, rows=size.lines)
    sys.stdout.write('\x1b[2J\x1b[H\x1b[48;2;24;44;64m\x1b[37mInteractive terminal fixture\r\n')
    sys.stdout.flush()
    received = b''
    while True:
        if not select.select([sys.stdin], [], [], 1)[0]:
            continue
        value = os.read(sys.stdin.fileno(), 4096)
        if not value:
            break
        emit('input', data=value.hex())
        received += value
        sys.stdout.write('\x1b[10;1H\x1b[2KReceived '+received.hex()[-100:]+'\r\n')
        sys.stdout.flush()
finally:
    termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, original)

#!/usr/bin/env python3
"""Owned raw Wayland fixture: TITLE /tmp/LOG.jsonl [/tmp/STATE.json].

Uses the same small wire-protocol approach as pointer.py, without extra packages.
Stdin accepts lock/confine/destroy commands; logs acknowledge compositor roundtrips.
The optional snapshot records exact xdg_toplevel suspension configuration.
No desktop connection or input occurs at import time.
"""
import array
from collections import deque
import json
import os
from pathlib import Path
import select
import socket
import struct
import sys
import time


def uint(*values):
    return struct.pack('I'*len(values), *values)


def string(value):
    data = value.encode()+b'\0'
    return uint(len(data))+data+b'\0'*((-len(data)) % 4)


class Fixture:
    def __init__(self, title, log, state_path=None):
        self.log = log
        self.state_path = state_path
        self.configure_revision = 0
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(3)
        self.sock.connect(os.path.join(os.environ['XDG_RUNTIME_DIR'], os.environ.get('WAYLAND_DISPLAY', 'wayland-1')))
        self.buffer = b''
        self.next_id = 4
        self.objects = {1:'display', 2:'registry', 3:'registry-sync'}
        self.globals = {}
        self.callbacks = {}
        self.sent = deque(maxlen=24)
        self.constraint = None
        self.alive = True
        self.ready = False
        self.width, self.height = 500, 350
        self.send(1, 1, uint(2))
        self.send(1, 0, uint(3))
        self.registry_ready = False
        while not self.registry_ready:
            self.read()
        self.compositor = self.bind('wl_compositor', 4)
        self.shm = self.bind('wl_shm', 1)
        self.wm = self.bind('xdg_wm_base', 6)
        self.seat = self.bind('wl_seat', 5)
        self.manager = self.bind('zwp_pointer_constraints_v1', 1)
        self.surface = self.new('surface')
        self.send(self.compositor, 0, uint(self.surface))
        self.xdg = self.new('xdg-surface')
        self.send(self.wm, 2, uint(self.xdg, self.surface))
        self.toplevel = self.new('toplevel')
        self.send(self.xdg, 1, uint(self.toplevel))
        self.send(self.toplevel, 2, string(title))
        self.send(self.toplevel, 3, string('org.windowstash.ConstraintFixture'))
        self.send(self.toplevel, 7, uint(self.width, self.height))
        self.send(self.toplevel, 8, uint(self.width, self.height))
        self.pointer = self.new('pointer')
        self.send(self.seat, 0, uint(self.pointer))
        self.keyboard = self.new('keyboard')
        self.send(self.seat, 1, uint(self.keyboard))
        self.send(self.surface, 6)

    def emit(self, event, **fields):
        with self.log.open('a') as output:
            output.write(json.dumps(dict(event=event, time=time.monotonic(), **fields))+'\n')

    def new(self, kind):
        value = self.next_id
        self.next_id += 1
        self.objects[value] = kind
        return value

    def send(self, obj, opcode, payload=b'', fd=None):
        self.sent.append(dict(object=obj, kind=self.objects.get(obj), opcode=opcode, bytes=len(payload)))
        message = uint(obj, ((len(payload)+8) << 16) | opcode)+payload
        if fd is None:
            self.sock.sendall(message)
        else:
            sent = self.sock.sendmsg([message], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [fd]))])
            if sent < len(message):
                self.sock.sendall(message[sent:])

    def bind(self, interface, version):
        if interface not in self.globals:
            raise RuntimeError('Missing Wayland global: '+interface)
        name, available = self.globals[interface]
        value = self.new(interface)
        self.send(2, 0, uint(name)+string(interface)+uint(min(version, available), value))
        return value

    def sync(self, callback):
        value = self.new('callback')
        self.callbacks[value] = callback
        self.send(1, 0, uint(value))

    def draw(self):
        width, height = self.width, self.height
        size = width*height*4
        fd = os.memfd_create('window-stash-constraint-test', os.MFD_CLOEXEC)
        try:
            os.ftruncate(fd, size)
            pixel = struct.pack('I', 0xff286b82)
            os.write(fd, pixel*(width*height))
            pool, buffer = self.new('pool'), self.new('buffer')
            self.send(self.shm, 0, uint(pool, size), fd=fd)
            self.send(pool, 0, uint(buffer, 0, width, height, width*4, 0))
            self.send(pool, 1)
            self.send(self.surface, 1, uint(buffer, 0, 0))
            self.send(self.surface, 2, uint(0, 0, width, height))
            self.send(self.surface, 6)
        finally:
            os.close(fd)
        if not self.ready:
            self.ready = True
            self.sync(lambda: self.emit('ready', width=width, height=height))

    def read(self):
        data, ancillary, _, _ = self.sock.recvmsg(65536, socket.CMSG_SPACE(32*4))
        if not data:
            raise RuntimeError('Wayland connection closed')
        for level, kind, data_fds in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                values = array.array('i')
                values.frombytes(data_fds[:len(data_fds)//values.itemsize*values.itemsize])
                for fd in values:
                    os.close(fd)
        self.buffer += data
        while len(self.buffer) >= 8:
            obj, header = struct.unpack_from('II', self.buffer)
            size = header >> 16
            if size < 8:
                raise RuntimeError('Invalid Wayland event size')
            if len(self.buffer) < size:
                break
            payload, self.buffer = self.buffer[8:size], self.buffer[size:]
            self.event(obj, header & 0xffff, payload)

    def event(self, obj, opcode, payload):
        kind = self.objects.get(obj)
        if obj == 1 and opcode == 0:
            raise RuntimeError('Wayland protocol error: '+repr(payload)+'; recent requests: '+repr(list(self.sent)))
        if obj == 1 and opcode == 1:
            deleted, = struct.unpack_from('I', payload)
            self.objects.pop(deleted, None)
            return
        if obj == 2 and opcode == 0:
            name, length = struct.unpack_from('II', payload)
            interface = payload[8:8+length-1].decode()
            version, = struct.unpack_from('I', payload, 8+((length+3)//4)*4)
            self.globals[interface] = name, version
        elif obj == 3:
            self.registry_ready = True
        elif kind == 'callback':
            callback = self.callbacks.pop(obj, None)
            if callback:
                callback()
        elif kind == 'xdg_wm_base' and opcode == 0:
            self.send(obj, 3, payload)  # pong(serial)
        elif kind == 'xdg-surface' and opcode == 0:
            self.send(obj, 4, payload)  # ack_configure(serial)
            self.draw()
        elif kind == 'toplevel' and opcode == 0:
            width, height, length = struct.unpack_from('iiI', payload)
            states = struct.unpack_from('I'*(length//4), payload, 12)
            self.configure_revision += 1
            self.emit('configure', width=width, height=height, states=states)
            if self.state_path:
                temporary = self.state_path.with_suffix('.next')
                temporary.write_text(json.dumps(dict(pid=os.getpid(), suspended=9 in states,
                                                      revision=self.configure_revision, states=states)))
                temporary.replace(self.state_path)
        elif kind == 'toplevel' and opcode == 1:
            self.alive = False
        elif kind == 'buffer' and opcode == 0:
            # This static fixture allocates only on configure. Keep its few
            # buffers until disconnect, avoiding release/reconfigure lifetime
            # races that are unrelated to pointer-constraint acceptance.
            pass
        elif kind in ('lock', 'confine'):
            self.emit('constraint-state', kind=kind, active=opcode == 0)
        elif kind == 'keyboard' and opcode in (1, 2):
            self.emit('keyboard-enter' if opcode == 1 else 'keyboard-leave')
        elif kind == 'pointer' and opcode == 3:
            _, _, button, state = struct.unpack_from('IIII', payload)
            self.emit('button', button=button, pressed=bool(state))

    def command(self, request):
        action = request['action']
        if action == 'destroy':
            if self.constraint:
                self.send(self.constraint, 0)
                self.constraint = None
        elif action in ('lock', 'confine'):
            if self.constraint:
                raise RuntimeError('Destroy the previous constraint first')
            region = self.new('region')
            self.send(self.compositor, 1, uint(region))
            self.send(region, 1, uint(8, 8, 24, 24))
            self.constraint = self.new(action)
            self.send(self.manager, 1 if action == 'lock' else 2,
                      uint(self.constraint, self.surface, self.pointer, region, 2))
            self.send(region, 0)
            if action == 'lock':
                self.send(self.constraint, 1, struct.pack('ii', 20*256, 20*256))
            self.send(self.surface, 6)
        else:
            raise ValueError('Unknown fixture command: '+action)
        self.sync(lambda: self.emit('command', action=action, serial=request['serial']))

    def run(self):
        while self.alive:
            readable, _, _ = select.select([self.sock, sys.stdin], [], [], 3)
            if self.sock in readable:
                self.read()
            if sys.stdin in readable:
                line = sys.stdin.readline()
                if not line:
                    break
                self.command(json.loads(line))


def main():
    if len(sys.argv) not in (3, 4):
        raise SystemExit(__doc__)
    log = Path(sys.argv[2])
    assert log.is_absolute() and log.resolve().is_relative_to('/tmp')
    state_path = Path(sys.argv[3]) if len(sys.argv) == 4 else None
    assert state_path is None or (state_path.is_absolute() and state_path.resolve().is_relative_to('/tmp'))
    fixture = Fixture(sys.argv[1], log, state_path)
    try:
        fixture.run()
    finally:
        fixture.sock.close()


if __name__ == '__main__':
    main()

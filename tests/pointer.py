"""Tiny test-only Wayland virtual pointer client (wlroots virtual-pointer v1)."""
import os
import socket
import struct
import time


class Pointer:
    def __init__(self):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(3)
        self.sock.connect(os.path.join(os.environ['XDG_RUNTIME_DIR'], os.environ.get('WAYLAND_DISPLAY', 'wayland-1')))
        self.buffer = b''
        self.send(1, 1, self.uint(2))  # wl_display.get_registry
        self.send(1, 0, self.uint(3))  # sync
        manager = None
        while True:
            obj, opcode, payload = self.receive()
            if obj == 2 and opcode == 0:
                name, length = struct.unpack_from('II', payload)
                iface = payload[8:8+length-1].decode()
                if iface == 'zwlr_virtual_pointer_manager_v1': manager = name
            if obj == 3: break
        if manager is None: raise RuntimeError('Compositor does not offer virtual-pointer')
        self.send(2, 0, self.uint(manager)+self.string('zwlr_virtual_pointer_manager_v1')+self.uint(1)+self.uint(4))
        self.send(4, 0, self.uint(0)+self.uint(5))  # create_virtual_pointer, null seat
        self.sync()

    @staticmethod
    def uint(n): return struct.pack('I', n)

    @staticmethod
    def string(value):
        data = value.encode()+b'\0'
        return struct.pack('I', len(data))+data+b'\0'*((-len(data))%4)

    def send(self, obj, opcode, payload=b''):
        self.sock.sendall(struct.pack('II',obj,((len(payload)+8)<<16)|opcode)+payload)

    def receive(self):
        while len(self.buffer)<8: self.buffer+=self.sock.recv(65536)
        obj, header=struct.unpack_from('II',self.buffer)
        size=header>>16
        while len(self.buffer)<size: self.buffer+=self.sock.recv(65536)
        payload=self.buffer[8:size];self.buffer=self.buffer[size:]
        if obj==1 and header & 0xffff==0: raise RuntimeError('Wayland protocol error: '+repr(payload))
        return obj,header & 0xffff,payload

    def sync(self):
        self.send(1,0,self.uint(6))
        while True:
            obj,_,_=self.receive()
            if obj==6: break

    def move(self,x,y,width,height):
        self.send(5,1,b''.join(self.uint(int(n)) for n in (int(time.monotonic()*1000)&0xffffffff,x,y,width,height)))
        self.send(5,4)
        self.sync()

    def button(self,pressed,button=272):
        self.send(5,2,b''.join(self.uint(n) for n in (int(time.monotonic()*1000)&0xffffffff,button,int(pressed))))
        self.send(5,4)
        self.sync()

    def click(self,x,y,width,height,button=272):
        self.move(x,y,width,height);time.sleep(.05)
        self.button(True,button);time.sleep(.05);self.button(False,button)

    def close(self): self.sock.close()

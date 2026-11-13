#!/usr/bin/python3
"""Responsive, undecorated GTK source: TITLE LOG_PATH [APP_ID]."""
import json
import math
from pathlib import Path
import sys
import time

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk


if len(sys.argv) not in (3, 4):
    raise SystemExit(__doc__)
title, log_path = sys.argv[1], Path(sys.argv[2])
assert log_path.is_absolute() and log_path.resolve().is_relative_to('/tmp')
application = Gtk.Application(
    application_id=sys.argv[3] if len(sys.argv) == 4 else 'org.windowstash.AspectFixture',
    flags=Gio.ApplicationFlags.NON_UNIQUE)


def emit(kind, **fields):
    with log_path.open('a') as output:
        output.write(json.dumps(dict(event=kind, time=time.monotonic(), **fields))+'\n')


def activate(app):
    window = Gtk.ApplicationWindow(application=app, title=title)
    window.set_decorated(False)
    window.set_default_size(800, 600)
    canvas = Gtk.DrawingArea()
    canvas.set_size_request(80, 60)
    canvas.set_focusable(True)
    window.set_child(canvas)
    state = {'allocation': None}

    def draw(area, context, width, height):
        allocation = (width, height)
        if state['allocation'] != allocation:
            state['allocation'] = allocation
            emit('allocation', width=width, height=height, wide=width >= height,
                 fullscreen=window.is_fullscreen())
        context.set_source_rgb(.04, .09, .16)
        context.paint()
        # The banner changes with the real client allocation. The circle is
        # drawn in device-independent pixels, exposing nonuniform stretching.
        context.set_source_rgb(*((.1, .75, .3) if width >= height else (.9, .3, .08)))
        context.rectangle(0, 0, width, height*.12)
        context.fill()
        context.set_source_rgb(1, 1, 1)
        context.arc(width/2, height/2, min(width, height)*.2, 0, math.tau)
        context.fill()

    canvas.set_draw_func(draw)
    click = Gtk.GestureClick()
    click.set_button(0)
    click.connect('pressed', lambda gesture, count, x, y:
                  (emit('press', button=gesture.get_current_button(), x=x, y=y), canvas.grab_focus()))
    click.connect('released', lambda gesture, count, x, y:
                  emit('release', button=gesture.get_current_button(), x=x, y=y))
    canvas.add_controller(click)
    keys = Gtk.EventControllerKey()
    keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

    def pressed(controller, keyval, keycode, modifiers):
        name = Gdk.keyval_name(keyval)
        emit('key', name=name)
        if name == 'F11':
            window.unfullscreen() if window.is_fullscreen() else window.fullscreen()
            return True
        if name == 'Escape' and window.is_fullscreen():
            window.unfullscreen()
            return True
        return False

    keys.connect('key-pressed', pressed)
    window.add_controller(keys)
    window.connect('notify::fullscreened', lambda widget, _property:
                   emit('fullscreen', active=widget.is_fullscreen()))
    window.present()
    canvas.grab_focus()
    GLib.idle_add(lambda: (emit('ready'), GLib.SOURCE_REMOVE)[1])


application.connect('activate', activate)
application.run([sys.argv[0]])

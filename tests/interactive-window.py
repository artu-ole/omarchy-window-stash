#!/usr/bin/python3
"""Owned GTK input fixture: TITLE LOG_PATH [APP_ID]. Runtime data stays in /tmp."""
import json
from pathlib import Path
import sys
import time

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk

if len(sys.argv) not in (3, 4):
    raise SystemExit(__doc__)
title, log_path = sys.argv[1], Path(sys.argv[2])
assert log_path.is_absolute() and log_path.resolve().is_relative_to('/tmp')
app = Gtk.Application(application_id=sys.argv[3] if len(sys.argv) == 4 else 'org.windowstash.InteractiveFixture',
                      flags=Gio.ApplicationFlags.NON_UNIQUE)


def emit(kind, **fields):
    with log_path.open('a') as output:
        output.write(json.dumps(dict(event=kind, time=time.monotonic(), **fields))+'\n')


def activate(application):
    window = Gtk.ApplicationWindow(application=application, title=title)
    window.set_decorated(False)
    window.set_default_size(1000, 700)
    fixed = Gtk.Fixed()
    window.set_child(fixed)
    canvas = Gtk.DrawingArea()
    canvas.set_content_width(1000)
    canvas.set_content_height(700)
    canvas.set_focusable(True)
    canvas.set_cursor_from_name('crosshair')
    fixed.put(canvas, 0, 0)
    state = dict(clicks=0, moves=0, keys='', drag=False, popup=None, dialog=None)

    def draw(area, context, width, height):
        colors = ((.12, .24, .38), (.28, .16, .35), (.1, .32, .25), (.38, .24, .1))
        for index, color in enumerate(colors):
            context.set_source_rgb(*color)
            context.rectangle((index % 2)*width/2, (index//2)*height/2, width/2, height/2)
            context.fill()
        context.set_source_rgb(.9, .9, .9)
        context.select_font_face('monospace')
        context.set_font_size(24)
        context.move_to(32, 150)
        context.show_text('Interactive fixture: '+str(state['clicks'])+' clicks; '+str(state['moves'])+' moves')
        context.move_to(32, 190)
        context.show_text('Keys: '+state['keys'][-50:])

    canvas.set_draw_func(draw)
    motion = Gtk.EventControllerMotion()
    motion.connect('enter', lambda controller, x, y: emit('enter', x=x, y=y))
    motion.connect('leave', lambda controller: emit('leave'))

    def moved(controller, x, y):
        state['moves'] += 1
        emit('motion', x=x, y=y, dragging=state['drag'])
        canvas.queue_draw()

    motion.connect('motion', moved)
    canvas.add_controller(motion)
    click = Gtk.GestureClick()
    click.set_button(0)

    def pressed(gesture, count, x, y):
        state['clicks'] += 1
        state['drag'] = True
        emit('press', button=gesture.get_current_button(), count=count, x=x, y=y)
        canvas.grab_focus()
        canvas.queue_draw()

    def released(gesture, count, x, y):
        state['drag'] = False
        emit('release', button=gesture.get_current_button(), count=count, x=x, y=y)

    click.connect('pressed', pressed)
    click.connect('released', released)
    canvas.add_controller(click)
    scrolling = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.BOTH_AXES)

    def scrolled(controller, dx, dy):
        emit('scroll', dx=dx, dy=dy)
        return True

    scrolling.connect('scroll', scrolled)
    canvas.add_controller(scrolling)
    keys = Gtk.EventControllerKey()

    def key_pressed(controller, keyval, keycode, modifiers):
        name = Gdk.keyval_name(keyval) or ''
        state['keys'] += chr(Gdk.keyval_to_unicode(keyval)) if Gdk.keyval_to_unicode(keyval) else '['+name+']'
        emit('key-press', name=name, keyval=keyval, keycode=keycode, modifiers=int(modifiers))
        canvas.queue_draw()
        return False

    keys.connect('key-pressed', key_pressed)
    keys.connect('key-released', lambda controller, keyval, keycode, modifiers:
                 emit('key-release', name=Gdk.keyval_name(keyval), keycode=keycode, modifiers=int(modifiers)))
    canvas.add_controller(keys)
    entry = Gtk.Entry()
    entry.set_placeholder_text('Type, select and paste here')
    entry.set_size_request(300, 44)
    entry.connect('changed', lambda widget: emit('text', text=widget.get_text()))
    fixed.put(entry, 24, 24)
    popup_button = Gtk.Button(label='Popup')
    popup_button.set_size_request(120, 44)
    fixed.put(popup_button, 340, 24)

    def show_popup(button):
        if state['popup'] is not None:
            state['popup'].unparent()
        popup = Gtk.Popover()
        popup.set_parent(button)
        popup.set_autohide(True)
        popup.set_position(Gtk.PositionType.BOTTOM)
        item = Gtk.Button(label='Choose popup item')
        item.connect('clicked', lambda widget: (emit('popup-choice'), popup.popdown()))
        popup.set_child(item)
        popup.connect('closed', lambda widget: emit('popup-closed'))
        state['popup'] = popup
        popup.popup()
        emit('popup-open')

    popup_button.connect('clicked', show_popup)
    dialog_button = Gtk.Button(label='Modal dialog')
    dialog_button.set_size_request(150, 44)
    fixed.put(dialog_button, 480, 24)

    def show_dialog(button):
        dialog = Gtk.Window(application=application, title=title+' dialog', transient_for=window, modal=True)
        dialog.set_default_size(360, 180)
        child = Gtk.Button(label='Dismiss modal')
        child.connect('clicked', lambda widget: (emit('dialog-choice'), dialog.close()))
        dialog.set_child(child)
        state['dialog'] = dialog
        dialog.present()
        emit('dialog-open')

    dialog_button.connect('clicked', show_dialog)
    window.connect('close-request', lambda widget: (emit('close'), False)[1])
    window.present()
    canvas.grab_focus()
    GLib.idle_add(lambda: (emit('ready', width=canvas.get_width(), height=canvas.get_height()), GLib.SOURCE_REMOVE)[1])


app.connect('activate', activate)
app.run([sys.argv[0]])

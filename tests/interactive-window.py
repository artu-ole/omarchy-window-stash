#!/usr/bin/python3
"""Owned GTK input fixture: TITLE LOG_PATH [APP_ID]. Runtime data stays in /tmp."""
import json
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
app = Gtk.Application(application_id=sys.argv[3] if len(sys.argv) == 4 else 'org.windowstash.InteractiveFixture',
                      flags=Gio.ApplicationFlags.NON_UNIQUE)


def emit(kind, **fields):
    with log_path.open('a') as output:
        output.write(json.dumps(dict(event=kind, time=time.monotonic(), **fields))+'\n')


def activate(application):
    window = Gtk.ApplicationWindow(application=application, title=title)
    window.set_decorated(False)
    window.set_default_size(1000, 700)
    root_keys = Gtk.EventControllerKey()
    root_keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
    def root_key_pressed(controller, keyval, keycode, modifiers):
        name = Gdk.keyval_name(keyval)
        emit('root-key', name=name, keycode=keycode)
        if name == 'F11':
            emit('fullscreen-toggle', active=window.is_fullscreen())
            window.unfullscreen() if window.is_fullscreen() else window.fullscreen()
            return True
        if name == 'Escape' and window.is_fullscreen():
            emit('fullscreen-exit')
            window.unfullscreen()
            return True
        return False

    root_keys.connect('key-pressed', root_key_pressed)
    window.connect('notify::fullscreened', lambda widget, _property:
                   emit('fullscreen-state', active=widget.is_fullscreen(), width=widget.get_width(), height=widget.get_height()))
    window.add_controller(root_keys)
    css = Gtk.CssProvider()
    css.load_from_string('.stash-popup contents { background: #e64678; } .stash-popup button { background: #eb5a32; color: white; }')
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
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
        popup.add_css_class('stash-popup')
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

        def popup_layout():
            surface = popup.get_surface()
            if surface and hasattr(surface, 'get_position_x'):
                emit('popup-layout', x=surface.get_position_x(), y=surface.get_position_y(),
                     width=surface.get_width(), height=surface.get_height())
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(100, popup_layout)

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
    sibling_button = Gtk.Button(label='Sibling window')
    sibling_button.set_size_request(150, 44)
    fixed.put(sibling_button, 650, 24)

    def show_sibling(button):
        sibling = Gtk.ApplicationWindow(application=application, title=title+' sibling')
        sibling.set_default_size(500, 350)
        sibling.set_decorated(False)
        field = Gtk.Entry()
        field.set_placeholder_text('Same-client sibling keyboard target')
        field.connect('changed', lambda widget: emit('sibling-text', text=widget.get_text()))
        observer = Gtk.EventControllerKey()
        observer.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        observer.connect('key-pressed', lambda controller, keyval, keycode, modifiers:
                         (emit('sibling-key', name=Gdk.keyval_name(keyval), keycode=keycode), False)[1])
        field.add_controller(observer)
        sibling.set_child(field)
        sibling.connect('close-request', lambda widget: (emit('sibling-close'), False)[1])
        sibling.present()
        field.grab_focus()
        emit('sibling-open')

    sibling_button.connect('clicked', show_sibling)
    fullscreen_button = Gtk.Button(label='Full screen')
    fullscreen_button.set_size_request(150, 44)
    fullscreen_button.connect('clicked', lambda widget: (emit('fullscreen-request'), window.fullscreen()))
    fixed.put(fullscreen_button, 820, 24)
    existing_button = Gtk.Button(label='Existing transient')
    existing_button.set_size_request(180, 44)

    def show_existing(button):
        child = Gtk.Window(application=application, title=title+' existing', transient_for=window)
        child.set_default_size(320, 160)
        child.set_child(Gtk.Label(label='Pre-existing public transient'))
        child.present()
        emit('existing-open')

    existing_button.connect('clicked', show_existing)
    fixed.put(existing_button, 650, 84)
    move_button = Gtk.Button(label='Move request')
    move_button.set_size_request(150, 44)
    move_gesture = Gtk.GestureClick()
    move_gesture.set_button(1)
    move_gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

    def request_move(gesture, count, x, y):
        event = gesture.get_current_event()
        position = event.get_position()
        window.get_surface().begin_move(event.get_device(), 1, position[-2], position[-1], event.get_time())
        emit('move-request')

    move_gesture.connect('pressed', request_move)
    move_button.add_controller(move_gesture)
    fixed.put(move_button, 480, 84)
    activate_button = Gtk.Button(label='Activate request')
    activate_button.set_size_request(150, 44)
    activate_button.connect('clicked', lambda widget: (emit('activate-request'), window.get_surface().focus(Gdk.CURRENT_TIME)))
    fixed.put(activate_button, 820, 84)
    edge_button = Gtk.Button(label='Oversized popup')
    edge_button.set_size_request(150, 44)

    def show_edge(button):
        popup = Gtk.Popover()
        popup.set_parent(button)
        popup.set_autohide(True)
        child = Gtk.Label(label='A popup wider than the captured source needs the full window')
        child.set_size_request(1200, 120)
        popup.set_child(child)
        state['popup'] = popup
        popup.popup()
        emit('edge-popup-open')

    edge_button.connect('clicked', show_edge)
    fixed.put(edge_button, 820, 600)
    window.connect('close-request', lambda widget: (emit('close'), False)[1])
    window.present()
    canvas.grab_focus()
    GLib.idle_add(lambda: (emit('ready', width=canvas.get_width(), height=canvas.get_height()), GLib.SOURCE_REMOVE)[1])


app.connect('activate', activate)
app.run([sys.argv[0]])

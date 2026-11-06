#!/usr/bin/python3
"""Disposable GTK close target: TITLE APP_ID immediate|delay|prompt [DELAY_MS]."""
import sys
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GLib

if len(sys.argv) < 4 or sys.argv[3] not in ('immediate', 'delay', 'prompt'):
    raise SystemExit('usage: close-window.py TITLE APP_ID immediate|delay|prompt [DELAY_MS]')
title, app_id, mode = sys.argv[1:4]
delay = int(sys.argv[4]) if len(sys.argv) > 4 else 400
app = Gtk.Application(application_id=app_id, flags=Gio.ApplicationFlags.NON_UNIQUE)


def activate(application):
    window = Gtk.ApplicationWindow(application=application, title=title)
    window.set_default_size(640, 420)
    state = dict(allow=False, pending=False, dialog=None)

    def finish_close():
        state['allow'] = True
        window.close()
        return GLib.SOURCE_REMOVE

    def close_requested(target):
        if state['allow']:
            return False
        window.set_title(title + ' requested')
        if mode == 'immediate':
            return False
        if state['pending']:
            return True
        state['pending'] = True
        if mode == 'delay':
            GLib.timeout_add(delay, finish_close)
        else:
            dialog = Gtk.MessageDialog(transient_for=window, modal=True, text='Save changes?',
                                       secondary_text='Disposable close test: Cancel leaves the window open.')
            dialog.set_title(title + ' save changes')
            dialog.add_button('Cancel', Gtk.ResponseType.CANCEL)
            dialog.add_button('Close', Gtk.ResponseType.ACCEPT)
            dialog.set_default_response(Gtk.ResponseType.CANCEL)
            state['dialog'] = dialog

            def response(prompt, choice):
                prompt.destroy()
                state['dialog'] = None
                state['pending'] = False
                if choice == Gtk.ResponseType.ACCEPT:
                    finish_close()
                else:
                    window.set_title(title + ' cancelled')
            dialog.connect('response', response)
            dialog.present()
        return True

    window.connect('close-request', close_requested)
    button = Gtk.Button(label='Disposable Window Stash close target\n' + mode)
    button.connect('clicked', lambda unused: window.set_title(title + ' clicked'))
    window.set_child(button)
    window.present()


app.connect('activate', activate)
app.run([sys.argv[0]])

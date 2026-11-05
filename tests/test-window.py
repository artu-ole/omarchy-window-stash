#!/usr/bin/python3
"""Disposable GTK window for native Wayland and XWayland integration tests."""
import sys
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio

app=Gtk.Application(application_id=sys.argv[2] if len(sys.argv)>2 else 'org.windowstash.Test',flags=Gio.ApplicationFlags.NON_UNIQUE)
def activate(application):
    window=Gtk.ApplicationWindow(application=application,title=sys.argv[1] if len(sys.argv)>1 else 'Window Stash test')
    window.set_default_size(640,420)
    label=Gtk.Button(label='Disposable Window Stash test window\nClick to verify overlay input passes through.')
    label.connect('clicked',lambda button:window.set_title((sys.argv[1] if len(sys.argv)>1 else 'Window Stash test')+' clicked'))
    window.set_child(label)
    window.present()
app.connect('activate',activate)
app.run([sys.argv[0]])

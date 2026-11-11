#!/usr/bin/env python3
"""Focused DPMS capture diagnostics on a disposable, test-owned output.

Compare --compatibility standard and enhanced to distinguish compositor output
reflow from native rendering support. All geometry assertions remain enabled.
No existing output is powered off; NativeSession restores the desktop afterward.
"""
import argparse
import json

from desktop_test import desktop_test
from floating_previews import dpms_capture, drain, park, ready
from hover_previews import spawn_color
from live import configure, h, shell, wait
from native_session import NativeSession


@desktop_test('Floating preview disposable-output DPMS diagnostic')
def main(compatibility):
    with NativeSession() as session:
        for key, value in dict(presentation='previews', scope='workspace', grouping='app', animations='off',
                               hoverPreview='off', floatingPlacement='free', dragMotion='direct',
                               floatingPreviewSizing='free', floatingPreviewScale='100', floatingPreviewUpdate='still',
                               floatingPreviewTitles='hidden', floatingPreviewFrame='hidden', floatingPreviewLock='unlocked',
                               livePreviewCompatibility=compatibility).items():
            configure(key, value)
        existing = {monitor['name'] for monitor in h.read('monitors')}
        h.call('output', 'create', 'headless')
        monitor = wait(lambda: next((item for item in h.read('monitors') if item['name'] not in existing), None),
                       'Diagnostic output did not appear')
        session.outputs.append(monitor['name'])
        right = max(item['x']+round(item['width']/item['scale']) for item in h.read('monitors') if item['name'] != monitor['name'])
        h.eval('hl.monitor({output=%s,mode="320x240@60",position=%s,scale=1})' %
               (json.dumps(monitor['name']), json.dumps('%dx0' % right)))
        session.monitor = wait(lambda: next((item for item in h.read('monitors') if item['name'] == monitor['name']
                                and item['width'] == 320 and item['height'] == 240 and item['scale'] == 1), None),
                               'Diagnostic output mode did not apply')
        session.move(160, 120)
        h.dispatch('focus', monitor=monitor['name'])
        h.dispatch('focus', workspace=str(session.workspace+3))
        records = [park(session, spawn_color(session, color, app='org.windowstash.FloatingDpms', workspace=session.workspace+3))
                   for color in ('red', 'green', 'blue')]
        ready(session)
        dpms_capture(session, records, compatibility == 'enhanced', diagnostics=True)
        drain()
        assert not shell('status')['error'], shell('status')['error']
    drain()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compatibility', choices=('standard', 'enhanced'), default='enhanced')
    options = parser.parse_args()
    main(options.compatibility)

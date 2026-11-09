#!/usr/bin/env python3
"""Preserving native checks for bubble input and keyboard chooser restoration.

Plugin installation and removal belong to the disposable-profile CLI suite in
plugin_cli.py; this suite leaves the installed plugin and real stash intact.
"""
from desktop_test import desktop_test
from live import command, configure, h, shell, wait
from native_session import NativeSession
from stash import SPECIAL


def window_key(record):
    return 'window:'+str(record.get('stableId') or record['id'])


@desktop_test('Window Stash UI routing and restoration tests')
def main():
    with NativeSession() as t:
        for key, value in dict(presentation='bubbles', scope='workspace', grouping='window',
                               floatingPlacement='free', dragMotion='direct', hoverPreview='off',
                               animations='off', animationSpeed='normal', sizePreset='100',
                               iconShape='square', iconOpacity=100, restoreDestination='current',
                               dockSide='bottom', staticDockLock='locked').items():
            configure(key, value)
        first, first_title = t.spawn(app='org.windowstash.UiLifecycle')
        second, second_title = t.spawn(app='org.windowstash.UiLifecycle')
        area = t.surface()['usableArea']
        width, height = min(640, int(area['width'])-40), min(420, int(area['height'])-100)
        x, y = t.monitor['x']+round(area['x'])+20, t.monitor['y']+round(area['y'])+50
        for address in (first, second):
            h.dispatch('window.float', window='address:'+address, action='on')
            h.dispatch('window.resize', window='address:'+address, x=width, y=height, relative=False)
            h.dispatch('window.move', window='address:'+address, x=x, y=y, relative=False)
            wait(lambda: (c := h.client(address)) and c['floating']
                 and c['at'] == [x, y] and c['size'] == [width, height], 'Fixture geometry did not settle')

        record = t.park(first)
        key = window_key(record)
        t.position(key, round(area['x']+area['width']-64), round(area['y']+area['height']-64))
        h.dispatch('focus', window='address:'+second)
        # Empty regions of the bubble surface must preserve native GTK input.
        t.pointer.click(*t.point(x-t.monitor['x']+width/2, y-t.monitor['y']+height/2))
        wait(lambda: h.client(second)['title'] == second_title+' clicked', 'Bubble surface swallowed an outside click')
        t.click(t.icon(key))
        wait(lambda: h.client(first)['workspace']['id'] == t.workspace, 'Bubble click did not restore its window')
        wait(lambda: all(w['id'] != record['id'] for w in command('list')['windows']), 'Restored bubble kept its stash record')
        assert h.client(first)['floating'] and h.client(first)['at'] == [x, y] and h.client(first)['size'] == [width, height]
        print('PASS bubble input passthrough, direct restoration and floating geometry', flush=True)

        t.park(first)
        second_record = t.park(second)
        configure('presentation', 'dock')
        configure('grouping', 'app')
        group_key = 'app:'+second_record['app'].lower()
        wait(lambda: t.surface()['groups'] == 1 and t.icon(group_key), 'App group did not appear')
        t.click(t.icon(group_key))
        wait(lambda: shell('status')['dialog'] == 'picker' and t.surface()['dialog']['visible']
             and t.surface()['pickerCount'] == 2, 'Grouped icon did not open its chooser')
        t.keys(first_title)
        wait(lambda: t.surface()['pickerCount'] == 1, 'Chooser keyboard search failed')
        t.keys('-k', 'Return')
        wait(lambda: h.client(first)['workspace']['id'] == t.workspace, 'Chooser Enter did not restore the filtered window')
        assert h.client(second)['workspace']['name'] == SPECIAL, 'Chooser restored an unselected app window'
        wait(lambda: not t.surface()['dialog']['visible'], 'Chooser remained over the restored window')
        print('PASS grouped chooser keyboard focus, search and specific Enter restoration', flush=True)

        record = t.park(first)
        configure('presentation', 'bubbles')
        configure('grouping', 'window')
        configure('scope', 'global')
        h.dispatch('focus', workspace=str(t.workspace+1))
        wait(lambda: t.surface()['workspaceId'] == t.workspace+1 and t.icon(window_key(record)),
             'Original-destination fixture did not reach the invoking workspace')
        t.click(t.icon(window_key(record)), 273)
        wait(lambda: t.menu()['visible'], 'Bubble context menu did not open')
        assert t.menu()['targetIds'] == [record['id']]
        assert t.menu()['workspace'] == t.workspace+1
        t.click(t.action('original')['rect'])
        wait(lambda: h.client(first)['workspace']['id'] == t.workspace, 'Context action ignored the original workspace')
        assert h.client(second)['workspace']['name'] == SPECIAL, 'Original restore touched another stashed window'
        assert not shell('status')['error'], shell('status')['error']
        print('PASS icon-specific original-workspace restore from another workspace', flush=True)


if __name__ == '__main__':
    main()

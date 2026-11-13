#!/usr/bin/env python3
"""Production Settings detection, Later and bridge-only reload acceptance."""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
import time

from bridge_upgrade import build, native, require_isolated, unload_owned
from desktop_test import desktop_test
from floating_previews import park, ready, seed
from interactive_bridge import spawn_fixture
from live import ROOT, command, configure, h, shell, wait
from native_session import NativeSession
from stash import SPECIAL


def support():
    return shell('status')['bridgeSupport']


@contextmanager
def owned_bridge_cleanup():
    # The initial isolation guard requires an absent bridge. NativeSession
    # exits first, closing our sources and destroying their capture helpers.
    try:
        yield
    finally:
        if native():
            wait(lambda:not native()['owners'] and not native()['interaction'],
                 'Test-owned preview bridge did not become idle during cleanup',timeout=6)
            unload_owned()


def visible_control(session,pane,name):
    viewport=session.surface()['settingsScroll']['rect']
    dialog=session.surface()['dialog']
    rect=pane[name]
    assert rect['width']>0 and rect['height']>0 and rect['x']>=viewport['x']-.5 \
        and rect['y']>=viewport['y']-.5 \
        and rect['x']+rect['width']<=viewport['x']+viewport['width']+.5 \
        and rect['y']+rect['height']<=viewport['y']+viewport['height']+.5, \
        ('Preview support control is outside its visible Settings viewport',name,rect,viewport,session.surface()['dialog'])
    assert rect['x']>=dialog['x']-.5 and rect['y']>=dialog['y']-.5 \
        and rect['x']+rect['width']<=dialog['x']+dialog['width']+.5 \
        and rect['y']+rect['height']<=dialog['y']+dialog['height']+.5, \
        ('Preview support control is outside the Settings dialog',name,rect,dialog)


def settings_pane(session,later=False):
    """Wait for modelDelay and QML layout, not just local visible bindings."""
    previous=None
    since=0
    def settled():
        nonlocal previous,since
        surface=session.surface()
        pane=surface['bridgeSupport']
        signature=(surface['dialog'],surface['settingsScroll']['rect'],pane['reloadRect'],pane['laterRect'])
        if signature!=previous:
            previous=signature;since=time.monotonic();return None
        if not surface['dialog']['visible'] or time.monotonic()-since<.15:
            return None
        return pane if pane['visible'] and pane['reloadVisible'] and pane['reloadEnabled'] \
            and (not later or pane['laterVisible']) else None
    return wait(settled,'Preview support Settings controls did not settle')


@desktop_test('Isolated preview support upgrade Settings acceptance')
def acceptance(old_root):
    require_isolated()
    assert not native(), 'Use a fresh disposable profile with no loaded bridge'
    shell('checkPreviewSupport')
    wait(lambda:support()['status'].get('state')=='absent','Service did not observe the empty initial bridge state')
    with owned_bridge_cleanup(), tempfile.TemporaryDirectory(prefix='stash-upgrade-ui-') as temporary, NativeSession() as session:
        directory=Path(temporary)
        configure('presentation','dock');configure('hoverPreview','off')
        cache=Path(os.environ.get('XDG_CACHE_HOME',Path.home()/'.cache'))/'omarchy/window-stash/preview-bridge'
        old=build(old_root,cache/h.read('version')['commit']/'ui-upgrade-fixture')
        build(ROOT,cache,modern=True)
        h.call('plugin','load',old['path'])
        wait(lambda:native().get('version')==old['version'],'Owned old UI bridge did not load')
        shell('checkPreviewSupport')
        state=wait(lambda:(value:=support())['status'].get('state')=='update-required' and value,
                   'Service did not detect its outdated native bridge')
        assert state['status']['canReload'] is True,state
        shell('settings')
        pane=settings_pane(session,later=True)
        visible_control(session,pane,'laterRect')
        session.click(pane['laterRect'])
        wait(lambda:support()['deferred'],'Actual Later button did not defer the update')
        assert native()['version']==old['version'],'Later replaced native code'
        pane=session.surface()['bridgeSupport']
        assert pane['reloadVisible'] and pane['reloadEnabled'] and not pane['laterVisible'],pane
        shell('checkPreviewSupport')
        wait(lambda:not support()['checking'],'Deferred status check did not finish')
        assert support()['deferred'],'Polling forgot the user deferral'
        print('PASS proactive mismatch detection, actual Settings Later action, retained reload action and deferral across polls',flush=True)

        shell('dismiss')
        for key,value in dict(presentation='previews',scope='workspace',grouping='window',
                              floatingPreviewUpdate='live',livePreviewCompatibility='enhanced',
                              floatingPreviewInteraction='on',floatingPreviewActivation='explicit',
                              floatingPreviewKeyboard='click',floatingPlacement='free',dragMotion='direct',
                              animations='off').items():
            configure(key,value)
        address=spawn_fixture(session,directory/'source.jsonl')
        control,_=session.spawn(app='org.windowstash.UpgradeUiControl')
        record=park(session,address)
        seed(session,record,140,120,320)
        h.dispatch('focus',window='address:'+control)
        source=h.client(address)
        original=(source['workspace'],source['at'],source['size'],source['floating'])
        display_before={monitor['name']:{key:monitor.get(key) for key in ('x','y','width','height','scale','transform')}
                        for monitor in h.read('monitors')}
        saved=command('list')
        shell('settings')
        pane=settings_pane(session)
        visible_control(session,pane,'reloadRect')
        before_pointer=h.read('cursorpos')
        session.click(pane['reloadRect'])
        try:
            state=wait(lambda:(value:=support())['status'].get('state')=='current' and not value['busy'] and value,
                       'Actual Settings reload did not finish',timeout=30)
        except AssertionError:
            print('Settings reload diagnostics:',support(),session.surface()['bridgeSupport'],
                  {'dialog':shell('status')['dialog'],'surfaces':[(item['screen'],item['dialog']) for item in shell('status')['surfaces']],
                   'beforePointer':before_pointer,'afterPointer':h.read('cursorpos')},flush=True)
            raise
        assert not state['error'],state
        actual=native()
        assert actual['version']==(ROOT/'native/version.txt').read_text().strip(),actual
        assert shell('status')['dialog']=='settings','Reload closed the user Settings window'
        assert not shell('status')['previewInteraction']['request'], 'Reload unexpectedly entered input interaction'
        shell('dismiss')
        wait(lambda:record['id'] in shell('status')['previewCompatibility']['status'].get('ids',[])
             and shell('status')['previewCompatibility']['running'],
             'Visible Enhanced live capture did not resume after reload')
        wait(lambda:ready(session,record)['image']['live'],'The live miniature did not resume capture')
        current=h.client(address)
        assert (current['workspace'],current['at'],current['size'],current['floating'])==original \
            and current['workspace']['name']==SPECIAL,'UI reload changed or restored the hidden source'
        after=command('list')
        assert after['settings']==saved['settings'] and after['positions']==saved['positions'], \
            'UI reload changed preferences or saved geometry'
        assert h.client(control) and h.read('activeworkspace')['id']==session.workspace
        assert {monitor['name']:{key:monitor.get(key) for key in ('x','y','width','height','scale','transform')}
                for monitor in h.read('monitors')}==display_before,'Bridge reload changed output geometry'
        print('PASS actual Settings reload replaces only the bridge, resumes Enhanced capture, preserves preferences/windows/geometry and leaves interaction inactive',flush=True)
        configure('presentation','dock');configure('hoverPreview','off')
        wait(lambda:not shell('status')['previewCompatibility']['running'],'Capture helper did not stop for cleanup')
        wait(lambda:not native()['owners'] and not native()['interaction'],'Native owners remained after capture cleanup')
        unload_owned()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-root',type=Path,required=True)
    acceptance(parser.parse_args().old_root.resolve())

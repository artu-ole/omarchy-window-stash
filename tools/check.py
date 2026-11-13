#!/usr/bin/env python3
"""Run non-graphical checks with the installed Qt6/Omarchy import environment."""
from pathlib import Path
import json
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
def run(*args):subprocess.run(args,cwd=ROOT,check=True)

manifest=json.loads((ROOT/'manifest.json').read_text())
for field in ('id','name','version','author','description','license'):
    value=manifest.get(field)
    if not isinstance(value,str) or not value.strip():
        raise SystemExit('Publishing metadata missing a nonempty string: '+field)
if len(manifest['version'])>64:
    raise SystemExit('Marketplace version display is limited to 64 characters')
for name in ('README.md','LICENSE','THIRD_PARTY_NOTICES.md'):
    if not (ROOT/name).is_file() or not (ROOT/name).read_text().strip():
        raise SystemExit('Missing publication document: '+name)
print('Publishing metadata and documents passed',flush=True)

# Native suites are not imported by unittest discovery. Compile them without
# execution so syntax errors cannot hide until desktop automation starts.
sources=sorted(p for directory in ('controller','tests','tools') for p in (ROOT/directory).rglob('*.py'))
for source in sources:
    compile(source.read_text(),str(source.relative_to(ROOT)),'exec',dont_inherit=True)
print(f'Python syntax passed for {len(sources)} source and test files',flush=True)

run('python3','-m','unittest','discover','-s','tests','-v')
run('node','tests/model.test.cjs')
run('node','tests/matryoshka.test.cjs')
run('node','tests/jumping.test.cjs')
run('node','tests/sizing.test.cjs')
run('node','tests/floating_panel.test.cjs')
run('node','tests/animation_speed.test.cjs')
run('node','tests/stack_follow.test.cjs')
run('node','tests/preview_model.test.cjs')
run('node','tests/preview_capture.test.cjs')
run('node','tests/preview_visibility.test.cjs')
run('node','tests/floating_preview_model.test.cjs')
run('node','tests/preview_interaction_model.test.cjs')
run('node','tests/preview_activation.test.cjs')
run('node','tests/preview_folding_keeper.test.cjs')
run('node','tests/context_clicks.test.cjs')
run('node','tests/drag_physics.test.cjs')
run('python3','tests/collection_model.py')
run('python3','tests/drag_world.py')
run('python3','tests/stack_follow_qt.py')
run('python3','tests/static_dock_position.py')
run('python3','tests/floating_preview_cards_qt.py')
run('python3','tests/preview_geometry_keeper_qt.py')
run('python3','tests/preview_aspect_cards_qt.py')
run('python3','tests/preview_keeper_qt.py')
run('python3','tests/preview_interaction_keeper_qt.py')
run('python3','tests/preview_interaction_cards_qt.py')
run('python3','tests/preview_interactive_resize_qt.py')
run('python3','tests/preview_super_click_qt.py')
run('python3','tests/preview_folding_qt.py')
run('python3','tests/preview_shortcut_keeper_qt.py')
run('python3','tests/preview_keyboard_focus_qt.py')
run('python3','tests/bridge_upgrade_qt.py')
run('python3','tests/workspace_state_qt.py')
run('omarchy','plugin','validate',str(ROOT))
with tempfile.TemporaryDirectory(prefix='window-stash-qml-') as directory:
    qs=Path(directory)/'qs';qs.mkdir()
    (qs/'Commons').symlink_to('/usr/share/omarchy/shell/Commons',target_is_directory=True)
    (qs/'Ui').symlink_to('/usr/share/omarchy/shell/Ui',target_is_directory=True)
    run('/usr/lib/qt6/bin/qmllint','-I',directory,'-I','/usr/lib/qt6/qml',
        'Service.qml',*[str(p.relative_to(ROOT)) for p in sorted((ROOT/'ui').glob('*.qml'))])
print('All controller, model, manifest and Qt6 QML checks passed.')

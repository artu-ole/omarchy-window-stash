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

run('python3','-m','unittest','discover','-s','tests','-v')
run('node','tests/model.test.cjs')
run('node','tests/matryoshka.test.cjs')
run('node','tests/floating_panel.test.cjs')
run('node','tests/animation_speed.test.cjs')
run('node','tests/stack_follow.test.cjs')
run('node','tests/preview_model.test.cjs')
run('node','tests/preview_capture.test.cjs')
run('node','tests/drag_physics.test.cjs')
run('python3','tests/collection_model.py')
run('python3','tests/drag_world.py')
run('python3','tests/stack_follow_qt.py')
run('omarchy','plugin','validate',str(ROOT))
with tempfile.TemporaryDirectory(prefix='window-stash-qml-') as directory:
    qs=Path(directory)/'qs';qs.mkdir()
    (qs/'Commons').symlink_to('/usr/share/omarchy/shell/Commons',target_is_directory=True)
    (qs/'Ui').symlink_to('/usr/share/omarchy/shell/Ui',target_is_directory=True)
    run('/usr/lib/qt6/bin/qmllint','-I',directory,'-I','/usr/lib/qt6/qml',
        'Service.qml',*[str(p.relative_to(ROOT)) for p in sorted((ROOT/'ui').glob('*.qml'))])
print('All controller, model, manifest and Qt6 QML checks passed.')

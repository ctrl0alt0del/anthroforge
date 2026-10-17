"""Load planned backup primaries in factory Blender before retiring backups."""
import json
import sys
from pathlib import Path
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from storage_support import fingerprint, safe, save


def probe(root, entry):
    path = safe(root, entry['primary'])
    try:
        bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False, use_scripts=False)
        if not bpy.data.scenes or not bpy.data.objects:
            raise ValueError('Primary contains no scene or objects')
        actual = fingerprint(path)
        if actual != entry['newer']: raise ValueError('Primary changed since planning')
        return dict(path=entry['primary'], status='loaded', objects=len(bpy.data.objects), **actual)
    except Exception as error:
        return dict(path=entry['primary'], status='error', error=str(error))


def main():
    root, run = (Path(value).resolve(strict=True) for value in sys.argv[sys.argv.index('--') + 1:])
    plan = json.loads((run / 'backup_plan.json').read_text())
    entries = [e for e in plan['entries'] if e['action'] == 'remove']
    results = []
    for index, entry in enumerate(entries, 1):
        result = probe(root, entry); results.append(result)
        save(run / 'backup_blender_load.json', results)
        print(json.dumps(dict(index=index, total=len(entries), **result)), flush=True)
    if any(r['status'] != 'loaded' for r in results): raise RuntimeError('Some primaries did not load')


if __name__ == '__main__':
    main()

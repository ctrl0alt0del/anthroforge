"""Final staged skeleton exercise, retaining every report and native output copy."""
import hashlib
import json
import sys
from pathlib import Path
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from authoring_visual_skeleton import anthroforge, run_stage, StaticScene


def main():
    source, folder = map(Path, sys.argv[sys.argv.index('--')+1:])
    folder.mkdir(parents=True, exist_ok=True)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    if not hasattr(bpy.types.Object, 'af_scp_system'):
        anthroforge.register()
    bpy.ops.wm.open_mainfile(filepath=str(source))
    records = stages(folder, source)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    report = dict(source=str(source), source_sha256=before, original_unchanged=True, stages=records, anatomical_review='unreviewed')
    (folder/'verification_report.json').write_text(json.dumps(report, indent=2))
    print('VISUAL_RELEASE_STAGES_PASS', flush=True)


def stages(folder, source):
    results = {}
    for stage in ('views', 'points', 'regions', 'adopt', 'interaction'):
        root = bpy.data.objects['AF_ROOT']
        result = run_stage(root, folder, stage)
        (folder/('stage_'+stage+'.json')).write_text(json.dumps(dict(results=result), indent=2))
        target = folder/('skeleton_visual_'+stage+'.blend')
        assert target.resolve() != source.resolve()
        StaticScene(root, bpy.context.scene).save_copy(target)
        results[stage] = dict(state='pass', report=str(folder/('stage_'+stage+'.json')), scene=str(target))
        if stage == 'adopt':
            bpy.ops.wm.open_mainfile(filepath=str(target))
    return results


if __name__ == '__main__':
    main()

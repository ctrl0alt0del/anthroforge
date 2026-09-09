"""Generic protocol authoring exercise on an untouched-input skeleton copy."""
import hashlib
import json
import sys
from pathlib import Path
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
import anthroforge
from anthroforge.app.authoring.api import execute
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.core.authoring.migration import migrate
from anthroforge.core.authoring.packages import rewrite
from anthroforge.core.authoring.validation import document as validate_document

SOURCE = Path('E:/development/WIP_models/skeleton_comb_base.blend1')
PREVIOUS = Path('E:/development/WIP_models/dsl_experiment_v03_final')
OUTPUT = Path('E:/development/WIP_models/dsl_experiment_v04')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def send(root, operation, journal, **params):
    inventory = StaticScene(root, bpy.context.scene).capture_authoring()
    params['scene_id'] = root.name
    if operation not in ('discover', 'inspect', 'requirements', 'export', 'explain', 'validate'):
        params['expected_scene_revision'] = inventory['revision']
    number = len(list(OUTPUT.glob('request_*.json')))
    request = dict(version='0.4.0', message_type='request', request_id='exercise_'+str(number), op='anatomy.'+operation, params=params)
    (OUTPUT/f'request_{number:03}.json').write_text(json.dumps(request, indent=2))
    result = execute(request, root, bpy.context.scene, journal)
    (OUTPUT/f'response_{number:03}.json').write_text(json.dumps(result, indent=2))
    print('V04_OPERATION', operation, params.get('document_id', ''), result['status'], flush=True)
    return result


def authored(root, filename, label):
    old = json.loads((PREVIOUS/filename).read_text())
    inventory = StaticScene(root, bpy.context.scene).capture_authoring()
    bindings = {r['scp_id']: r['instance_id'] for r in inventory['instances'] if not r['mirror'] and r['has_surface']}
    value = migrate(old, bindings)
    value['document_id'] = 'static_'+label
    value['scenarios'] = {}
    value['skeleton_profiles']['default']['controls'] = controls(inventory)
    for policy in value['policies'].values():
        policy['refinement'] = dict(method='none')
        policy.update(total_budget_ms=120000, solver_budget_ms=30000)
    validate_document(value)
    (OUTPUT/(value['document_id']+'.json')).write_text(json.dumps(value, indent=2))
    return value


def controls(inventory):
    proof = dict(basis='designer_authored', sources=[], note='Native construction control; anatomical role awaits binding review.')
    return {'control_'+str(i): dict(instance_id=row['instance_id'], kind=row['kind'], reference_digest=row['digest'], evidence=proof) for i, row in enumerate(inventory['controls'])}


def run_document(root, journal, value):
    key = value['document_id']
    context = send(root, 'discover', journal)['assets'][0]
    draft = send(root, 'draft', journal, document_id=key, document=value, expected_draft_revision=0)
    send(root, 'checkpoint', journal, document_id=key, expected_draft_revision=1)
    send(root, 'inspect', journal, document_id=key)
    compiled = send(root, 'compile', journal, document_id=key, expected_draft_revision=1)
    if compiled['status'] == 'success':
        published = send(root, 'publish', journal, document_id=key, expected_draft_revision=1)
    else:
        published = dict(published=False)
    return dict(document_id=key, draft=draft['status'], compilation=compiled, published=published, inventory_asset=context)


def variant(root, journal, value):
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
    root, journal = bpy.data.objects['AF_ROOT'], OUTPUT/'variant_journal'
    send(root, 'initialize', journal)
    obj = next(o for o in bpy.context.scene.objects if o.get('af_scp_id') == 'SCP_13' and o.get('af_scp_geometry') and not o.get('af_scp_mirror'))
    obj.scale.x *= 1.12
    bpy.context.view_layer.update()
    value = proportion_document(root, value)
    result = run_document(root, journal, value)
    StaticScene(root, bpy.context.scene).save_copy(OUTPUT/'skeleton_static_proportion.blend')
    return result


def proportion_document(root, value):
    value = json.loads(json.dumps(value))
    value['document_id'] += '_proportion'
    profile = value['skeleton_profiles'].pop('default')
    inventory = StaticScene(root, bpy.context.scene).capture_authoring()
    instances = {r['scp_id']: r['instance_id'] for r in inventory['instances'] if not r['mirror'] and r['has_surface']}
    for binding in profile['bindings'].values():
        binding['instance_id'] = instances[binding['scp_id']]
    profile['controls'] = controls(inventory)
    value = replace_profile(value)
    value['skeleton_profiles']['proportion'] = replace_profile(profile)
    return value


def replace_profile(value):
    if isinstance(value, dict):
        return {k: replace_profile(v) for k, v in value.items()}
    if isinstance(value, list):
        return [replace_profile(v) for v in value]
    return value.replace('/skeleton_profiles/default', '/skeleton_profiles/proportion') if isinstance(value, str) else value


def main():
    before = sha(SOURCE)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if not hasattr(bpy.types.Object, 'af_scp_system'):
        anthroforge.register()
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
    root, journal = bpy.data.objects['AF_ROOT'], OUTPUT/'journal'
    send(root, 'initialize', journal)
    send(root, 'discover', journal)
    finish(root, journal, before)


def finish(root, journal, before):
    specs = [('muscle_belly_dsl.json', 'biceps'), ('muscle_2011_dsl.json', 'pectoral'), ('muscle_2005_dsl.json', 'spinal')]
    values = [authored(root, filename, label) for filename, label in specs]
    results = [run_document(root, journal, value) for value in values]
    StaticScene(root, bpy.context.scene).save_copy(OUTPUT/'skeleton_static_reference.blend')
    checkpoint = send(root, 'checkpoint', journal, document_id=values[0]['document_id'], expected_draft_revision=1)
    changed = variant(root, journal, values[0])
    report = dict(original_sha256=before, original_unchanged=sha(SOURCE) == before, results=results, variant=changed, checkpoint=checkpoint, anatomical_review='unreviewed', units='scene-relative, uncalibrated')
    (OUTPUT/'exercise_report.json').write_text(json.dumps(report, indent=2))
    print('V04_EXERCISE_COMPLETE', report['original_unchanged'], flush=True)


if __name__ == '__main__':
    main()

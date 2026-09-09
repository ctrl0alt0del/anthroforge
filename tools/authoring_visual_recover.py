"""Verify the adopted regions through a recovered scene's adjacent journal."""
import json
import sys
from pathlib import Path
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from authoring_visual_skeleton import anthroforge, send, execute, validate


def query(root, operation, **params):
    request = dict(version='0.4.0', message_type='request', request_id='recovered_'+operation+'_'+str(params.get('query', 'export')), op='anatomy.'+operation, params=dict(scene_id=root.name, document_id='visual_regions_demo', **params))
    result = execute(request, root, bpy.context.scene)
    validate(result, 'protocol')
    assert result['status'] == 'success', result
    return result


def main():
    folder = Path(sys.argv[sys.argv.index('--')+1])
    if not hasattr(bpy.types.Object, 'af_scp_system'):
        anthroforge.register()
    bpy.ops.wm.open_mainfile(filepath=str(folder/'skeleton_visual_adopt.blend'))
    root = bpy.data.objects['AF_ROOT']
    generation = json.loads((folder/'stage_adopt.json').read_text())['results']['checkpoint']['generation']['id']
    target = folder/'recovered'/'skeleton_visual.blend'
    result = send(root, folder, 'recover', generation_id=generation, output_path=str(target))
    bpy.ops.wm.open_mainfile(filepath=str(target))
    verify_recovered(folder, result)


def verify_recovered(folder, recovery):
    root = bpy.data.objects['AF_ROOT']
    exported = query(root, 'export')
    regions = exported['document']['skeleton_profiles']['default']['regions']
    assert len(regions) == 3
    results = {key: query(root, 'query', query=dict(kind='region', reference='/skeleton_profiles/default/regions/'+key))['matches'][0] for key in regions}
    assert all(row['area'] > 0 for row in results.values())
    report = dict(recovery=recovery, regions=results, adjacent_journal_used=True, state='pass')
    (folder/'recovery_verification.json').write_text(json.dumps(report, indent=2))
    print('VISUAL_RECOVERY_PASS', flush=True)


if __name__ == '__main__':
    main()

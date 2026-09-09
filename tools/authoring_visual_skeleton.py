"""Stage-by-stage visual authoring verification on a separate skeleton copy."""
import hashlib
import json
import sys
from pathlib import Path
import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import anthroforge
from anthroforge.app.authoring.api import execute
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.core.authoring.schema import validate
from anthroforge.core.authoring import visual_camera as camera
from anthroforge.core.authoring import visual_mesh as mesh, visual_raster as raster


def send(root, folder, operation, expect='success', **params):
    params['scene_id'] = root.name
    request = dict(version='0.4.0', message_type='request', request_id=operation+'_'+str(len(list(folder.glob('*request.json')))), op='anatomy.'+operation, params=params)
    stem = str(len(list(folder.glob('*request.json')))).zfill(4)
    (folder/(stem+'_request.json')).write_text(json.dumps(request, indent=2))
    result = execute(request, root, bpy.context.scene, folder/'journal')
    (folder/(stem+'_response.json')).write_text(json.dumps(result, indent=2))
    validate(result, 'protocol')
    assert result['status'] == expect, result
    print('VISUAL_STAGE', operation, 'PASS', flush=True)
    return result


def subjects(inventory):
    return [r for r in inventory['instances'] if r['scp_id'] in ('SCP_13', 'SCP_4', 'SCP_1') and r['has_surface'] and not r['mirror']]


def stage_views(root, folder):
    inventory = StaticScene(root, bpy.context.scene).capture_authoring()
    send(root, folder, 'initialize', expected_scene_revision=inventory['revision'])
    inventory = StaticScene(root, bpy.context.scene).capture_authoring()
    result = {}
    for row in subjects(inventory):
        views = send(root, folder, 'views', instance_id=row['instance_id'], expected_scene_revision=inventory['revision'])
        points = camera.vertices(inventory['geometry'][row['instance_id']])
        errors = [float(np.max(abs(camera.unproject(v['camera'], camera.project(v['camera'], points))-points))) for v in views['views']]
        assert max(errors) < 1e-9, errors
        result[row['scp_id']] = dict(instance_id=row['instance_id'], views=views['views'], roundtrip_error=max(errors), assets=views['assets'])
    return result


def main():
    source, output = map(Path, sys.argv[sys.argv.index('--')+1:][:2])
    output.mkdir(parents=True, exist_ok=True)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    stage = sys.argv[-1] if sys.argv[-1] in ('points', 'regions', 'adopt', 'interaction') else 'views'
    destination = output/('skeleton_visual_'+stage+'.blend')
    assert source.resolve() != destination.resolve()
    if not hasattr(bpy.types.Object, 'af_scp_system'):
        anthroforge.register()
    bpy.ops.wm.open_mainfile(filepath=str(source))
    root = bpy.data.objects['AF_ROOT']
    result = run_stage(root, output, stage)
    StaticScene(root, bpy.context.scene).save_copy(destination)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    (output/('stage_'+stage+'.json')).write_text(json.dumps(dict(source_sha256=before, results=result), indent=2))


def stage_points(root, folder):
    previous = fresh_views(root, folder)
    results = {}
    for key, subject in previous.items():
        view = subject['views'][6]
        inventory = StaticScene(root, bpy.context.scene).capture_authoring()
        scene = mesh.snapshot(inventory, subject['instance_id'])
        buffer = raster.render(scene, view['camera'])
        yx = np.argwhere(buffer['ids'] >= 0)[::max(1, np.count_nonzero(buffer['ids'] >= 0)//12)][:12]
        hits = send(root, folder, 'pick', view_id=view['id'], points=[[(int(x)+.5)/512, (int(y)+.5)/512] for y, x in yx])['hits']
        errors = [float(np.linalg.norm(np.asarray(h['barycentric']) @ buffer['mesh'][h['triangle']]-h['point'])) for h in hits]
        assert max(errors) < 1e-8 and all(h['on_requested_owner'] for h in hits)
        confirmation = send(root, folder, 'highlight', view_ids=[v['id'] for v in subject['views']], point_ids=[hits[len(hits)//2]['id']])
        results[key] = dict(hits=hits, barycentric_error=max(errors), native_bvh_error=native_hits(scene, view, hits), confirmation=confirmation)
    return results


def native_hits(scene, view, hits):
    from mathutils.bvhtree import BVHTree
    geometry = scene['geometry'][scene['owner']]
    vertices = camera.vertices(geometry)
    triangles = vertices[np.asarray(geometry['triangles'])]
    tree = BVHTree.FromPolygons(vertices.tolist(), geometry['triangles'], all_triangles=True)
    errors = []
    for hit in hits:
        origin, direction, _ = camera.ray(view['camera'], hit['uv'], triangles)
        native = tree.ray_cast(origin.tolist(), direction.tolist())[0]
        assert native is not None
        errors.append(float(np.linalg.norm(np.asarray(native)-hit['point'])))
    assert max(errors) < 1e-5, errors
    return max(errors)


def fresh_views(root, folder):
    result = stage_views(root, folder)
    (folder/'current_views.json').write_text(json.dumps(result, indent=2))
    return result


def run_stage(root, folder, stage):
    if stage == 'interaction':
        from authoring_visual_interaction import stage_interaction
        return stage_interaction(root, folder)
    if stage == 'adopt':
        from authoring_visual_adoption import stage_adopt
        return stage_adopt(root, folder)
    return {'views': stage_views, 'points': stage_points, 'regions': stage_regions}[stage](root, folder)


def stage_regions(root, folder):
    subjects = stage_views(root, folder)
    result = {}
    for key, subject in subjects.items():
        view = subject['views'][6]
        inventory = StaticScene(root, bpy.context.scene).capture_authoring()
        buffer = raster.render(mesh.snapshot(inventory, subject['instance_id']), view['camera'])
        yx = np.argwhere(buffer['ids'] >= 0)
        y, x = yx[len(yx)//2]
        u, v = (float(x)+.5)/512, (float(y)+.5)/512
        polygon = [[u-.06, v-.08], [u+.06, v-.08], [u+.06, v+.08], [u-.06, v+.08]]
        selected = send(root, folder, 'select_region', view_id=view['id'], polygon=polygon)
        result[key] = region_checks(root, folder, subject, selected, polygon)
    return result


def region_checks(root, folder, subject, selected, polygon):
    value, view = selected['selection'], subject['views'][6]
    assert value['area'] > 0 and value['patches']
    union = send(root, folder, 'select_region', view_id=view['id'], polygon=polygon, selection_id=value['id'], mode='add')['selection']
    assert abs(value['area']-union['area']) < 1e-7
    removed = send(root, folder, 'select_region', view_id=view['id'], polygon=polygon, selection_id=value['id'], mode='subtract')['selection']
    assert removed['area'] < 1e-7
    confirmed = send(root, folder, 'inspect_selection', selection_id=value['id'], view_ids=[v['id'] for v in subject['views']])
    return dict(subject=subject, selection=value, confirmation=confirmed, duplicate_area_error=abs(value['area']-union['area']), subtracted_area=removed['area'])


if __name__ == '__main__':
    main()

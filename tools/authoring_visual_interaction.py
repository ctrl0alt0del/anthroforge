"""Native skeleton camera, context, coverage, persistence and stale-view checks."""
import json
from pathlib import Path
import bpy
import numpy as np
from authoring_visual_skeleton import send, fresh_views
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.core.authoring import visual_camera as camera, visual_mesh as mesh, visual_raster as raster


def stage_interaction(root, folder):
    rows = fresh_views(root, folder)
    results = {key: inspect_subject(root, folder, value) for key, value in rows.items()}
    queries = [send(root, folder, 'query', document_id='visual_regions_demo', query=dict(kind='region', reference='/skeleton_profiles/default/regions/'+key)) for key in rows]
    results['reloaded_regions'] = [q['matches'][0] for q in queries]
    results['stale_view'] = stale_test(root, folder, rows['SCP_13'])
    return results


def inspect_subject(root, folder, subject):
    views = subject['views']
    first = send(root, folder, 'coverage', view_ids=[views[0]['id']])['coverage']
    all_views = send(root, folder, 'coverage', view_ids=[v['id'] for v in views])['coverage']
    assert all_views['observed_samples'] >= first['observed_samples']
    focused = focus(root, folder, subject)
    section = send(root, folder, 'view', view_id=views[6]['id'], section=dict(normal=views[6]['camera']['right'], distance=float(np.dot(views[6]['camera']['center'], views[6]['camera']['right']))), display=dict(edges=True, controls=True))
    inventory = StaticScene(root, bpy.context.scene).capture_authoring()
    context = [key for key in inventory['geometry'] if key != subject['instance_id']]
    contextual = send(root, folder, 'views', instance_id=subject['instance_id'], expected_scene_revision=inventory['revision'], resolution=256, context_ids=context)
    hidden = send(root, folder, 'view', view_id=contextual['views'][6]['id'], context_ids=[], point_id=focused['point']['id'])
    return dict(initial_coverage=first, coverage=all_views, focused=focused, section=section, contextual=contextual, hidden_context=hidden)


def focus(root, folder, subject):
    view = subject['views'][6]
    inventory = StaticScene(root, bpy.context.scene).capture_authoring()
    buffer = raster.render(mesh.snapshot(inventory, subject['instance_id']), view['camera'])
    visible = np.argwhere(buffer['ids'] >= 0)
    y, x = visible[len(visible)//2]
    hit = send(root, folder, 'pick', view_id=view['id'], points=[[(float(x)+.5)/512, (float(y)+.5)/512]])['hits'][0]
    result = send(root, folder, 'view', view_id=view['id'], point_id=hit['id'], zoom=2, display=dict(edges=True, controls=True))
    np.testing.assert_allclose(camera.project(result['view']['camera'], hit['point'])[:2], [.5, .5], atol=1e-12)
    return dict(result, point=hit)


def stale_test(root, folder, subject):
    inventory = StaticScene(root, bpy.context.scene).capture_authoring()
    row = next(r for r in inventory['instances'] if r['instance_id'] == subject['instance_id'])
    obj = bpy.data.objects[row['locator']]
    old = obj.scale.copy()
    try:
        obj.scale.x *= 1.01
        bpy.context.view_layer.update()
        result = send(root, folder, 'pick', expect='unresolved', view_id=subject['views'][0]['id'], points=[[.5, .5]])
        assert result['diagnostics'][0]['code'] == 'STALE_VIEW'
    finally:
        obj.scale = old
        bpy.context.view_layer.update()
    return result

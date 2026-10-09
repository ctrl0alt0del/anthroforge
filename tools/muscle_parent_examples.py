"""Build inspectable native abdominal Layer and pectoral Pouch attachment examples."""
from pathlib import Path
import os
import sys
import json
from math import sin, pi
REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO.parent), str(REPO / 'tests/blender'), str(REPO / 'tools')]
os.environ['AF_FIBER_ENGINE'] = 'V3'
import bpy
import numpy as np
from mathutils import Vector
from _helpers import reset_scene, root, scp_with_object, find_flagged, select_only
from anthroforge.core.id_utils import next_prefixed_id
from anthroforge.core.vcp import attachment_backend as bindings
from anthroforge.core.vcp.surface_reference import key
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.scp_runtime.prop_update_guard import suppress_scp_prop_updates
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from anthroforge.core.visualization.fiber_surface_sync import register_fiber_surface_sync
from anthroforge.core.visualization.muscle_sync import register_muscle_sync
from anthroforge.core.visualization.vcp_mirror_runtime import sync_vcp_mirrors
from anthroforge.app.use_cases.free_fiber import configure_mode


def skeletal_patch(owner, name, rectangle):
    x0,x1,y0,y1 = rectangle; mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(x0,y0,0), (x1,y0,0), (x1,y1,0), (x0,y1,0)], [], [(0,1,2,3)])
    obj = bpy.data.objects.new(name, mesh); bpy.context.scene.collection.objects.link(obj)
    with suppress_scp_prop_updates():
        scp = scp_with_object(owner, name, obj); scp.mirror_enabled = True
    return scp.id


def make_fiber(owner, parents, queries, name, lift=.025):
    with suppress_vcp_prop_updates():
        f = owner.af_vcp_system.fibers.add(); f.id = next_prefixed_id(owner.af_vcp_system.fibers, 'FIBER'); f.name = name
        f.thickness = .002; f.collision_radius = .001
        records = [None] + [f.mid_touches.add() for _ in queries[1:-1]] + [None]
        anchors = [_bind(owner, f, records, i, p, q) for i,(p,q) in enumerate(zip(parents, queries))]
    points = _path(anchors, lift)
    register_fiber_sync().apply_points(owner, bpy.context.scene, f, points, commit=True)
    configure_mode(owner, bpy.context.scene, f, 'FREE')
    return f.id


def _bind(owner, fiber, records, index, parent, query):
    raw = bindings.capture_attachment_from_world(owner, bpy.context.scene, parent, Vector(query))
    if index in (0,len(records)-1):
        side = 'a' if index == 0 else 'b'; setattr(fiber, side+'_parent_id', parent); setattr(fiber, side+'_attach_param', raw)
    else: records[index].parent_id, records[index].attach_param = parent, raw
    return bindings.resolve_attachment_world(owner, bpy.context.scene, parent, raw)


def _path(anchors, lift):
    rows = [a.lerp(b,i/12) + Vector((0,0,lift*sin(pi*i/12))) for a,b in zip(anchors,anchors[1:]) for i in range(12)]
    return rows + [anchors[-1]]


def loft(owner, ids, name, flip=False):
    from anthroforge.app.use_cases.fiber_surface_create import _new_surface, _assign_refs
    with suppress_vcp_prop_updates():
        surface = _new_surface(owner.af_vcp_system, name, 'LOFT', False, False); _assign_refs(surface, ids)
        surface.flip_normals = flip
    register_fiber_surface_sync().sync_root_to_scene(owner, bpy.context.scene, {surface.id})
    return surface.id


def muscle(owner, rectangle, name, amount):
    x0,x1,y0,y1 = rectangle; scp = skeletal_patch(owner, name+' skeletal support', rectangle)
    ids = [make_fiber(owner, [scp,scp], [(x0+.025,y,0),(x1-.025,y,0)], name+' base row', .025)
           for y in np.linspace(y0+.025,y1-.025,5)]
    sid = loft(owner, ids, name+' base', True)
    select_only(find_flagged('af_fiber_surface_proxy', sid, 'af_fiber_surface_id'))
    assert bpy.ops.af.create_muscle_from_fiber_surface(surface_id=sid) == {'FINISHED'}
    m = owner.af_vcp_system.muscles[-1]
    with suppress_vcp_prop_updates(): m.name = name; m.inflation_mode = 'DISTRIBUTED'; m.inflation_max_value = amount; m.flip_normals = True
    register_muscle_sync().sync_root_to_scene(owner, bpy.context.scene, {m.id})
    from anthroforge.core.deps.mirror_roles import apply_scp_mirror_roles
    apply_scp_mirror_roles(owner); sync_vcp_mirrors(owner, bpy.context.scene)
    return m.id


def make_tissue(owner, surface, preset, name):
    select_only(find_flagged('af_fiber_surface_proxy', surface, 'af_fiber_surface_id'))
    bpy.context.scene.af_new_soft_tissue_target_obj = None; bpy.context.scene.af_new_soft_tissue_preset = preset
    assert bpy.ops.af.add_soft_tissue_vcp() == {'FINISHED'}
    tissue = owner.af_vcp_system.soft_tissues[-1]
    with suppress_vcp_prop_updates():
        tissue.name = name; tissue.inflation_amount = .10 if preset == 'LAYER' else .20
        tissue.gravity = (0,-1,0); tissue.sagginess = .18; tissue.iterations = 350; tissue.tolerance = 1e-5
    from anthroforge.core.visualization.soft_tissue_sync import register_soft_tissue_sync
    register_soft_tissue_sync().sync_root_to_scene(owner, bpy.context.scene, {tissue.id}, force=True)
    sync_vcp_mirrors(owner, bpy.context.scene)
    return tissue.id


def abdominal():
    reset_scene(); owner = root(); ys = (-.6, 0., .6)
    mids = [muscle(owner, (.12,.68,y-.25,y+.25), 'Abdominal support '+str(i+1), .065) for i,y in enumerate(ys)]
    targets = [key(dict(type='MUSCLE', id=mid)) for mid in mids]
    ids = [make_fiber(owner, targets, [(x,y,1) for y in ys], 'Attached abdominal row', .10) for x in np.linspace(.23,.57,5)]
    sid = loft(owner, ids, 'Abdominal attached fiber surface')
    tissue = make_tissue(owner, sid, 'LAYER', 'Source-bound abdominal layer')
    return owner, tissue


def pectoral():
    reset_scene(); owner = root(); mid = muscle(owner, (.15,1.05,-.45,.45), 'Curved pectoral support', .16)
    target = key(dict(type='MUSCLE', id=mid))
    ids = [make_fiber(owner, [target,target], [(.3,y,1),(.9,y,1)], 'Attached pectoral row', .07)
           for y in np.linspace(-.25,.25,5)]
    sid = loft(owner, ids, 'Pectoral attached fiber surface', True)
    tissue = make_tissue(owner, sid, 'POUCH', 'Source-bound pectoral pouch')
    return owner, tissue


def inspect(owner, tissue_id):
    from anthroforge.core.visualization.free_fiber_runtime import current, anchor_points
    from anthroforge.core.vcp.free_path import tagged_indices
    from anthroforge.core.visualization.soft_tissue_sync import _evaluate_generic_tissue, register_soft_tissue_sync
    from anthroforge.core.vcp.soft_tissue_source_goals import source_goals
    residual = 0.
    for f in owner.af_vcp_system.fibers:
        payload, points = current(owner, bpy.context.scene, f)
        residual = max(residual, max((points[i]-p).length for i,p in zip(tagged_indices(payload),anchor_points(owner,bpy.context.scene,f))))
    tissue = next(t for t in owner.af_vcp_system.soft_tissues if t.id == tissue_id)
    result = _evaluate_generic_tissue(register_soft_tissue_sync(), owner, bpy.context.scene, tissue, 'NONE')
    fixed = max((Vector(result.final.vertices[i])-Vector(p)).length for mode,i,p,_s in source_goals(tissue,result.rest,result.sample) if mode=='FIXED')
    assert residual < 1e-5 and fixed < 1e-5, (residual,fixed)
    return dict(anchor_error=residual, fixed_goal_error=fixed, tissue_report=result.final.report, vertices=len(result.final.vertices))


def save(owner, tissue, output):
    from anthroforge.adapters.authoring.scene import StaticScene
    from muscle_parent_presentation import configure, render
    configure(owner, bpy.context.scene)
    evidence = inspect(owner, tissue); before = geometry(owner, tissue)
    StaticScene(owner, bpy.context.scene).save_debug_copy(str(output))
    bpy.ops.wm.open_mainfile(filepath=str(output)); owner = root()
    evidence['reopened'] = inspect(owner, tissue)
    after = geometry(owner, tissue); np.savez(output.with_suffix('.npz'), **{'before_'+k:v for k,v in before.items()}, **{'after_'+k:v for k,v in after.items()})
    evidence['persistence_errors'] = {k: float(np.max(np.abs(before[k]-after[k]))) if before[k].shape == after[k].shape else 'TOPOLOGY_CHANGED' for k in before}
    evidence.update(debug_visibility(owner))
    output.with_suffix('.json').write_text(json.dumps(evidence, indent=2))
    assert all(isinstance(v,float) and v < 1e-5 for k,v in evidence['persistence_errors'].items() if k != 'normals'), evidence
    render(bpy.context.scene, output.with_suffix('.png'))
    render(bpy.context.scene, output.with_name(output.stem+'_fibers.png'), True)


def debug_visibility(owner):
    from anthroforge.core.scp_runtime.object_colors import ensure_scp_color
    curves = [o for o in bpy.context.scene.objects if o.get('af_fiber_proxy')]
    assert all(o.type == 'CURVE' and o.display_type != 'WIRE' and not o.hide_get() and not o.hide_viewport and not o.hide_render for o in curves)
    assert sum(bool(o.get('af_fiber_mirror_proxy')) for o in curves) == len(owner.af_vcp_system.fibers)
    colors = {s.id: ensure_scp_color(owner,s) for s in owner.af_scp_system.scps}
    for obj in bpy.context.scene.objects:
        if obj.get('af_scp_geometry'): np.testing.assert_allclose(obj.color[:3], colors[obj.get('af_source_scp_id') or obj.get('af_scp_id')][:3], atol=1e-6)
        for kind in ('fiber', 'fiber_surface', 'muscle', 'soft_tissue'):
            if obj.get('af_'+kind+'_proxy'): assert obj.get('af_'+kind+'_output_state') == 'CURRENT', (obj.name, dict(obj))
    return dict(visible_curves=len(curves), mirrored_curves=sum(bool(o.get('af_fiber_mirror_proxy')) for o in curves))


def geometry(owner, tissue_id):
    from anthroforge.core.visualization.soft_tissue_sync import _evaluate_generic_tissue, register_soft_tissue_sync
    tissue = next(t for t in owner.af_vcp_system.soft_tissues if t.id == tissue_id)
    result = _evaluate_generic_tissue(register_soft_tissue_sync(), owner, bpy.context.scene, tissue, 'NONE')
    values = {k: np.asarray(v) for k,v in dict(points=result.sample.points, normals=result.sample.normals,
        weights=result.sample.weights, rest=result.rest.vertices, final=result.final.vertices).items()}
    return dict(values, **published_geometry())


def published_geometry():
    result = {}
    for obj in bpy.context.scene.objects:
        if not any(obj.get('af_'+kind+'_proxy') for kind in ('fiber', 'fiber_surface', 'muscle', 'soft_tissue')): continue
        if obj.type == 'CURVE': points = [obj.matrix_world @ Vector(p.co[:3]) for s in obj.data.splines for p in s.points]
        else: points = [obj.matrix_world @ p.co for p in obj.data.vertices]
        result[obj.name] = np.asarray(points)
    return result


def main():
    folder = Path(sys.argv[sys.argv.index('--output')+1]); folder.mkdir(parents=True, exist_ok=True)
    for name, build in (('abdominal_layer',abdominal), ('pectoral_pouch',pectoral)):
        owner, tissue = build(); save(owner,tissue,folder/(name+'.blend'))
        print('EXAMPLE_SAVED', name, flush=True)


if __name__ == '__main__': main()

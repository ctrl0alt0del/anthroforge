"""Read-only geometry/control discovery and explicit identity initialization."""
from uuid import uuid4
import bpy
from mathutils import Vector
from ...core.authoring.codec import digest
from ...core.authoring.errors import require
from .capture import native_records


def objects(root, scene):
    return [o for o in scene.objects if owned(o, root) and (o.get('af_scp_bound') or o.get('af_scp_mirror'))]


def owned(obj, root):
    identity = root.get('af_authoring_id')
    scope = obj.get('af_authoring_root_id')
    return scope == identity if scope and identity else obj.get('af_root_name') == root.name


def initialize(root, scene):
    targets = [root] + objects(root, scene)
    identities = [o.get('af_authoring_id') for o in targets if o.get('af_authoring_id')]
    require(len(set(identities)) == len(identities), 'DUPLICATED_IDENTITY')
    for obj in targets:
        if not obj.get('af_authoring_id'):
            obj['af_authoring_id'] = str(uuid4())
        if obj != root:
            obj['af_authoring_root_id'] = root['af_authoring_id']
    return capture(root, scene)


def capture(root, scene):
    bpy.context.view_layer.update()
    require(not root.get('af_authoring_id') or sum(o.get('af_authoring_id') == root['af_authoring_id'] for o in scene.objects) == 1, 'DUPLICATED_ROOT_IDENTITY')
    rows = [describe(o, root) for o in objects(root, scene)]
    ids = [r['instance_id'] for r in rows if r['instance_id']]
    require(len(ids) == len(set(ids)), 'DUPLICATED_IDENTITY')
    geometry = {r['instance_id'] or r['locator']: geometry_for(scene.objects[r['label']]) for r in rows if r['has_surface']}
    controls = [control_for(scene.objects[r['label']], r) for r in rows if r['control_kind']]
    instances = [r for r in rows if r['has_surface'] or r['control_kind'] == 'hook']
    native = _inventory_native(root)
    revision = digest([root.get('af_authoring_id', ''), stable(rows), geometry, stable(controls), native])
    return dict(root_id=root.get('af_authoring_id', ''), scene_id=root.name, revision=revision, reference_pose=str(root.get('af_authoring_pose', 'rest')), instances=instances, controls=controls, geometry=geometry, native=native)


def _inventory_native(root):
    native = native_records(root)
    for row in native['muscles']:
        for key in ('section_depths', 'section_peaks', 'section_roundness'):
            if key in row['values']:
                row['values'][key] = _profile_number(row['values'][key])
    return native


def _profile_number(value):
    from math import isfinite
    if isinstance(value, list):
        return [_profile_number(item) for item in value]
    return value if isfinite(value) else str(value)


def stable(rows):
    return [{k: v for k, v in row.items() if k not in ('label', 'locator')} for row in rows]


def describe(obj, root):
    scp_id = str(obj.get('af_source_scp_id') or obj.get('af_scp_id', ''))
    native = next((s for s in root.af_scp_system.scps if s.id == scp_id), None)
    mirror = bool(obj.get('af_scp_mirror'))
    concept = str(native.get('af_anatomical_concept', '')) if native else ''
    side = str(obj.get('af_anatomical_side', 'unknown'))
    return dict(instance_id='AFI_'+obj['af_authoring_id'] if obj.get('af_authoring_id') else '', locator=obj.name, label=obj.name, scp_id=scp_id, mirror=mirror, concept=concept, side=side, has_surface=obj.type == 'MESH' and bool(obj.get('af_scp_geometry')), control_kind=control_kind(obj))


def control_kind(obj):
    if obj.type == 'LATTICE':
        return 'lattice'
    if obj.type == 'EMPTY' and obj.get('af_scp_transform'):
        return 'hook'
    if obj.type == 'CURVE':
        return 'profile' if all(s.use_cyclic_u for s in obj.data.splines) else 'guide'
    return ''


def geometry_for(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        return dict(vertices=[list(v.co) for v in mesh.vertices], triangles=[list(t.vertices) for t in mesh.loop_triangles],
                    polygons=[list(p.vertices) for p in mesh.polygons], triangle_polygons=[t.polygon_index for t in mesh.loop_triangles],
                    matrix=[list(r) for r in evaluated.matrix_world])
    finally:
        evaluated.to_mesh_clear()


def control_for(obj, row):
    points = control_points(obj)
    supported = obj.type != 'CURVE' or all(s.type in ('BEZIER', 'POLY') for s in obj.data.splines)
    payload = dict(kind=row['control_kind'], points=points, matrix=[list(r) for r in obj.matrix_world], supported=supported)
    return dict(instance_id=row['instance_id'], locator=row['locator'], scp_id=row['scp_id'], digest=digest(payload), **payload)


def control_points(obj):
    if obj.type == 'LATTICE':
        return [list(obj.matrix_world @ p.co_deform) for p in obj.data.points]
    if obj.type != 'CURVE':
        return [list(obj.matrix_world.translation)]
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    points = [p for s in evaluated.data.splines for p in spline_points(s)]
    return [list(obj.matrix_world @ Vector(p)) for p in points]


def spline_points(spline):
    if spline.type != 'BEZIER':
        return [p.co.xyz for p in spline.points]
    from mathutils.geometry import interpolate_bezier
    points = list(spline.bezier_points)
    pairs = list(zip(points, points[1:]+points[:1])) if spline.use_cyclic_u else list(zip(points, points[1:]))
    samples = [p for a, b in pairs for p in interpolate_bezier(a.co, a.handle_right, b.handle_left, b.co, 17)[:-1]]
    return samples+([points[-1].co] if not spline.use_cyclic_u and points else [])

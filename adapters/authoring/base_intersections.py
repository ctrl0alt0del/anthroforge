"""Read published BASE proxies, including hidden objects; never rebuild geometry."""
from hashlib import sha256
from time import perf_counter
import numpy as np
from ...core.authoring.base_intersections import scan
from ...core.authoring.codec import digest


def diagnose(port, params):
    started = perf_counter(); meshes, issues, muscles = capture(port, params)
    report = scan(meshes, params.get('tolerance', 1e-7), params.get('witness_limit', 8))
    report['issues'] = issues+report['issues']
    report.update(kind='muscle_base_intersections.v1', complete=not report['issues'], scope='published_base_meshes',
        muscle_count=len(muscles), surface_count=len(meshes), tolerance=params.get('tolerance', 1e-7),
        surfaces=[m['identity'] for m in meshes], geometry_revision=geometry_revision(meshes),
        intersection_pair_count=sum(p['intersection'] for p in report['pairs']),
        contact_only_pair_count=sum(not p['intersection'] for p in report['pairs']), elapsed_ms=(perf_counter()-started)*1000)
    return report


def capture(port, params):
    muscles = {m.id: m for m in port.root.af_vcp_system.muscles}
    if len(muscles) != len(port.root.af_vcp_system.muscles): raise ValueError('BASE_DUPLICATE_MUSCLE_ID')
    selected = params.get('muscle_ids', list(muscles))
    if not set(selected) <= muscles.keys(): raise ValueError('BASE_UNKNOWN_MUSCLE')
    if len(set(selected)) != len(selected): raise ValueError('BASE_DUPLICATE_SELECTION')
    objects = [o for o in port.scene.objects if o.get('af_root_name') == port.root.name and o.get('af_muscle_proxy')]
    bases = [o for o in objects if o.get('af_muscle_surface') == 'BASE']
    meshes = []
    issues = [dict(code='BASE_ORPHAN', object_name=o.name) for o in bases if object_key(o)[0] not in muscles]
    for mid in sorted(selected):
        capture_muscle(port, muscles[mid], bases, objects, meshes, issues, params.get('include_mirrors', True))
    return meshes, issues, selected


def capture_muscle(port, muscle, bases, objects, meshes, issues, mirrors):
    for instance in ('source', 'mirror') if mirrors else ('source',):
        candidates = [o for o in bases if object_key(o) == (muscle.id, instance)]
        if instance == 'mirror' and not candidates and not expects_mirror(port, muscle, objects): continue
        label = dict(muscle_id=muscle.id, muscle_name=muscle.name, instance=instance)
        if len(candidates) != 1:
            issues.append(dict(code='BASE_MISSING' if not candidates else 'BASE_DUPLICATE', surface=label)); continue
        obj = candidates[0]; label.update(object_name=obj.name, surface_id=muscle.fiber_surface_id)
        try: meshes.append(read_mesh(obj, label))
        except (ValueError, RuntimeError) as error: issues.append(dict(code=str(error), surface=label))


def object_key(obj):
    mirror = bool(obj.get('af_muscle_mirror_proxy'))
    return (obj.get('af_source_muscle_id') if mirror else obj.get('af_muscle_id'), 'mirror' if mirror else 'source')


def expects_mirror(port, muscle, objects):
    from ...core.visualization.vcp_mirror_runtime import _rule_for_muscle, _scp_map
    if any(object_key(o) == (muscle.id, 'mirror') for o in objects): return True
    fibers = {f.id: f for f in port.root.af_vcp_system.fibers}
    return _rule_for_muscle(muscle, fibers, _scp_map(port.root)) is not None


def read_mesh(obj, identity):
    if obj.get('af_muscle_output_state', 'CURRENT') != 'CURRENT': raise ValueError('BASE_NOT_CURRENT')
    if obj.type != 'MESH': raise ValueError('BASE_NOT_MESH')
    # The native published base is the diagnostic subject; display modifiers must not substitute it.
    mesh = obj.data; mesh.calc_loop_triangles()
    vertices = np.empty((len(mesh.vertices), 3)); mesh.vertices.foreach_get('co', vertices.ravel())
    faces = np.empty((len(mesh.loop_triangles), 3), dtype=np.int64); mesh.loop_triangles.foreach_get('vertices', faces.ravel())
    polygons = np.empty(len(faces), dtype=np.int64); mesh.loop_triangles.foreach_get('polygon_index', polygons)
    matrix = np.asarray(obj.matrix_world, dtype=float); vertices = vertices@matrix[:3, :3].T+matrix[:3, 3]
    if not len(faces): raise ValueError('BASE_EMPTY_MESH')
    if not np.isfinite(vertices).all(): raise ValueError('BASE_COORDINATES')
    return dict(identity=identity, vertices=vertices, triangles=faces, polygons=polygons)


def geometry_revision(meshes):
    rows = [(m['identity'], *(sha256(m[k].tobytes()).hexdigest() for k in ('vertices', 'triangles'))) for m in meshes]
    return digest(rows)

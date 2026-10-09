"""Main-thread publication of final surfaces without changing intrinsic inputs."""
from dataclasses import replace
from contextlib import nullcontext
from time import perf_counter
import numpy as np
from ..muscle_pairs.capture import identity, _PUBLISHED, geometry

FINAL = {}
RECOVER = True


def forget(root_id=None, muscle=None):
    for key in tuple(FINAL):
        if (root_id is None or key[0] == root_id) and (muscle is None or key[1] == muscle): FINAL.pop(key)


def expected(root, muscle, obj, own, instance='source'):
    key = identity(root), muscle, instance
    value = FINAL.get(key)
    if value is not None: return value
    if RECOVER and obj is not None and obj.get('af_stacked_output'):
        write(obj, own); obj['af_stacked_output'] = False
    return own


def write(obj, world):
    from ..visualization.muscle_sync_helpers import update_mesh
    matrix = np.asarray(obj.matrix_world.inverted(), dtype=float)
    local = world @ matrix[:3, :3].T + matrix[:3, 3]
    faces = tuple(tuple(p.vertices) for p in obj.data.polygons)
    if obj.data.users > 1: obj.data = obj.data.copy()
    update_mesh(obj, local, faces)


def assembled(request, intrinsic, domains, surfaces, instance):
    selected = [v for v in domains if v.key.instance == instance]
    if intrinsic.side_a is None:
        values = intrinsic.inflated_vertices.copy()
        for d in selected: values[d.output_indices] = surfaces[d.key]
        return values
    from ..vcp.muscle_envelope import _compose
    a, b = intrinsic.side_a.copy(), intrinsic.side_b.copy()
    for d in selected: (a if d.key.side == 'A' else b)[d.output_indices] = surfaces[d.key]
    return _compose(request, replace(intrinsic, inflated_vertices=a), replace(intrinsic, inflated_vertices=b)).inflated_vertices


def targets(scope, backend):
    from ..visualization.muscle_sync_helpers import resolve_muscle_surface
    from ..muscle_pairs.capture import request_for
    scene, root = scope; outputs = backend.surfaces(); result = []
    for muscle in root.af_vcp_system.muscles:
        values = [v for v in backend.domains.values() if v.key.muscle == muscle.id and v.valid]
        if not values: continue
        request = request_for(root, scene, muscle); intrinsic = _PUBLISHED[(identity(root), muscle.id)][1]
        source = resolve_muscle_surface(root, muscle.id, 'INFL', scene)
        result.extend(muscle_targets(root, scene, muscle, source, request, intrinsic, values, outputs))
    return result


def muscle_targets(root, scene, muscle, source, request, intrinsic, domains, outputs):
    result = [(source, assembled(request, intrinsic, domains, outputs, 'source'), (identity(root), muscle.id, 'source'))]
    mirrors = [o for o in scene.objects if o.get('af_root_name') == root.name and o.get('af_muscle_mirror_proxy')
               and o.get('af_source_muscle_id') == muscle.id and o.get('af_muscle_surface') == 'INFL']
    for mirror in mirrors:
        mirror_request, mirrored = mirror_intrinsic(root, muscle.id, source, mirror, request, intrinsic)
        result.append((mirror, assembled(mirror_request, mirrored, domains, outputs, 'mirror'), (identity(root), muscle.id, 'mirror')))
    return result


def mirror_intrinsic(root, muscle, source, mirror, request, intrinsic):
    from ..muscle_pairs.capture import _MIRROR_PUBLISHED
    own = _MIRROR_PUBLISHED.get((identity(root), muscle))
    if mirror.get('af_independent_surface_instance') and own is not None: return own
    matrix = np.asarray(mirror.matrix_world @ source.matrix_world.inverted(), dtype=float)
    transform = lambda v: v @ matrix[:3, :3].T + matrix[:3, 3]
    return request, replace(intrinsic, inflated_vertices=transform(intrinsic.inflated_vertices),
        side_a=None if intrinsic.side_a is None else transform(intrinsic.side_a),
        side_b=None if intrinsic.side_b is None else transform(intrinsic.side_b))


def publish(scope, backend, summary, commit=None, guard=None):
    start = perf_counter(); values = targets(scope, backend)
    previous = [(obj, geometry(obj).copy(), obj.get('af_stacked_output')) for obj, _, _ in values]
    try:
        if guard: guard()
        with commit() if commit else nullcontext(): publish_transaction(scope, values)
    except BaseException:
        for obj, points, marker in previous: write(obj, points); obj['af_stacked_output'] = bool(marker)
        raise
    for _, points, key in values: FINAL[key] = points.copy()
    warning = notify_published(scope, values)
    if warning: summary['stacking']['notification_warning'] = warning
    summary['timings']['stack_publication_ms'] = (perf_counter()-start)*1000
    summary['stacking']['publication'] = 'published'


class PublicationAdapter:
    def __call__(self, scope, backend, summary, commit=None, guard=None):
        publish(scope, backend, summary, commit, guard)

    def prepare(self, scope):
        scene, root = scope
        for muscle in root.af_vcp_system.muscles: restore_intrinsic(scene, root, muscle.id)
        forget(identity(root))


def restore_intrinsic(scene, root, muscle_id):
    from ..visualization.muscle_sync_helpers import resolve_muscle_surface
    record = _PUBLISHED.get((identity(root), muscle_id))
    if record is None: return
    source = resolve_muscle_surface(root, muscle_id, 'INFL', scene)
    if source is None: return
    values = record[1].inflated_vertices
    if source.get('af_stacked_output'): write(source, values); source['af_stacked_output'] = False
    for obj in scene.objects:
        if obj.get('af_root_name') != root.name or obj.get('af_source_muscle_id') != muscle_id: continue
        if not obj.get('af_muscle_mirror_proxy') or obj.get('af_muscle_surface') != 'INFL': continue
        _request, intrinsic = mirror_intrinsic(root, muscle_id, source, obj, None, record[1])
        if obj.get('af_stacked_output'): write(obj, intrinsic.inflated_vertices); obj['af_stacked_output'] = False


def publish_transaction(scope, values):
    from .downstream import transaction, refresh
    scene, root = scope; muscles = {key[1] for _, _, key in values}
    with transaction(scene, root, muscles) as entities:
        for obj, points, _ in values: _write_publication(scope, obj, points)
        for obj, points, _ in values:
            if not np.allclose(geometry(obj), points, atol=5e-6, rtol=2e-6): raise ValueError('STACK_PUBLICATION_MISMATCH')
        refresh(scene, root, entities)


def notify_published(scope, values):
    from ..visualization.warning_runtime import notify_action
    scene, root = scope
    try:
        notify_action(root, scene, {'MUSCLE': {key[1] for _, _, key in values}})
        from .downstream import resume_fibers
        resume_fibers(scene, root, {key[1] for _, _, key in values})
    except (RuntimeError, ValueError, ReferenceError) as error: return str(error)


def _write_publication(scope, obj, points):
    from ..muscle_pairs.runtime import COORDINATOR, key
    write(obj, points); obj['af_stacked_output'] = True
    entry = COORDINATOR.entries.get(key(*scope))
    if entry: obj['af_stack_generation'] = entry.generation


def reapply(scene, root, muscle):
    for obj in scene.objects:
        if obj.get('af_root_name') != root.name or obj.get('af_muscle_surface') != 'INFL': continue
        instance = 'mirror' if obj.get('af_muscle_mirror_proxy') else 'source'
        if obj.get('af_source_muscle_id' if instance == 'mirror' else 'af_muscle_id') != muscle: continue
        values = FINAL.get((identity(root), muscle, instance))
        if values is not None: write(obj, values); obj['af_stacked_output'] = True

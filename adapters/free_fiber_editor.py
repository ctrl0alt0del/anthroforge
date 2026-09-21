"""Explicit native span editor. Draft objects never carry source-proxy tags."""
import copy
import json
from uuid import uuid4
import bpy
from mathutils import Matrix, Vector
from ..core.vcp import free_path, free_curve
from ..core.visualization import free_fiber_runtime as runtime
from ..app.use_cases import free_fiber as service

PREFIX = 'af_free_edit_'


def state(root, fiber):
    raw = root.get(PREFIX + fiber.id, '')
    return json.loads(raw) if raw else None


def save_state(root, fiber, value):
    root[PREFIX + fiber.id] = json.dumps(value, allow_nan=False)


def fingerprint(root, scene, fiber, depsgraph=None):
    from ..core.vcp.fiber_node_attachment import _surface_objects
    from ..core.vcp.fiber_node_attachment_codec import node_attachment_target_ids
    from ..core.vcp.fiber_authority import token
    objects = _surface_objects(scene, root); ids = node_attachment_target_ids(fiber)
    geometry = {key: _geometry(objects.get(key), scene, depsgraph) for key in ids}
    return free_path.digest(dict(authority=token(root, fiber), mode=fiber.behavior_mode,
        topology=fiber.topology_mode, symmetry=(fiber.symmetry_mode, fiber.symmetry_axis, list(fiber.symmetry_origin)),
        revision=fiber.free_path_revision, path=fiber.free_path_json, attachments=fiber.node_attachments_json,
        bindings=runtime.bindings(fiber), structure=runtime.structure(fiber), root=[list(r) for r in root.matrix_world], geometry=geometry))


def _geometry(obj, scene, depsgraph=None):
    if obj is None: return None
    from ..core.utils import depsgraph_for_scene
    evaluated = obj.evaluated_get(depsgraph if depsgraph is not None else depsgraph_for_scene(scene)); mesh = evaluated.to_mesh()
    try:
        return dict(matrix=[list(row) for row in obj.matrix_world], vertices=[list(v.co) for v in mesh.vertices],
                    faces=[list(face.vertices) for face in mesh.polygons])
    finally: evaluated.to_mesh_clear()


def open_edit(root, scene, fiber):
    if not free_path.is_free(fiber): raise ValueError('Edit Path requires Free mode.')
    if state(root, fiber): raise ValueError('EDIT_IN_PROGRESS')
    payload, points = runtime.current(root, scene, fiber)
    session = dict(version=1, id=str(uuid4()), fiber_id=fiber.id, fingerprint=fingerprint(root, scene, fiber),
                   payload=payload, opening=[list(p) for p in points], spans=[], stale=False, recovery=[])
    for indices in free_path.spans(points, free_path.tagged_indices(payload), fiber.topology_mode == 'LOOP'):
        session['spans'].append(_new_span(root, scene, session, [points[i] for i in indices], int(indices[0]), int(indices[-1])))
    session['initial_draft'] = draft(root, fiber, session)
    save_state(root, fiber, session)
    return objects(session)


def _collection(scene):
    collection = bpy.data.collections.get('AF_FREE_PATH_EDIT')
    if collection is None:
        collection = bpy.data.collections.new('AF_FREE_PATH_EDIT'); scene.collection.children.link(collection)
    return collection


def _new_span(root, scene, session, points, first, last):
    identity = str(uuid4()); curve = bpy.data.curves.new('AF_PathDraft', 'CURVE'); curve.dimensions = '3D'
    obj = bpy.data.objects.new('AF_PathDraft', curve); obj.matrix_world = root.matrix_world.copy()
    obj['af_free_editor_session'] = session['id']; obj['af_free_editor_span'] = identity
    obj['af_free_editor_root'] = root.name; obj['af_free_editor_fiber'] = session['fiber_id']
    _collection(scene).objects.link(obj); inverse = obj.matrix_world.inverted()
    _poly(curve, [inverse @ Vector(point) for point in points]); obj.show_in_front = True
    return dict(id=identity, first=first, last=last)


def _poly(curve, points):
    curve.splines.clear(); spline = curve.splines.new('POLY'); spline.points.add(len(points) - 1)
    spline.points.foreach_set('co', [v for p in points for v in (*p, 1.)])


def objects(session):
    return [obj for obj in bpy.data.objects if obj.get('af_free_editor_session') == session['id']]


def _span_object(session, span):
    found = [obj for obj in objects(session) if obj.get('af_free_editor_span') == span['id']]
    if len(found) != 1: raise ValueError('A structural editor span is missing or duplicated.')
    obj = found[0]
    if obj.type != 'CURVE' or len(obj.data.splines) != 1 or obj.modifiers or obj.constraints:
        raise ValueError('Keep exactly one unmodified native curve spline per structural span.')
    if obj.data.splines[0].use_cyclic_u or abs(obj.matrix_world.determinant()) < 1e-12:
        raise ValueError('Invalid cyclic span or noninvertible editor transform.')
    return obj


def draft(root, fiber, session=None):
    session = session or state(root, fiber)
    if session is None: raise ValueError('No path editing session.')
    if len(objects(session)) != len(session['spans']): raise ValueError('Unexpected joined, split or duplicate editor spans.')
    return [_read_span(_span_object(session, span), span) for span in session['spans']]


def _read_span(obj, span):
    spline = obj.data.splines[0]; matrix = obj.matrix_world
    if spline.type == 'POLY': values = [list(matrix @ Vector(p.co[:3])) for p in spline.points]
    elif spline.type == 'BEZIER': values = [_knot(p, matrix) for p in spline.bezier_points]
    else: raise ValueError('Only exact POLY and explicit Bézier editing are supported.')
    if len(values) < 2: raise ValueError('Structural span endpoints cannot be deleted.')
    return dict(id=span['id'], type=spline.type, values=values, matrix=[list(row) for row in matrix])


def _knot(point, matrix):
    return dict(co=list(matrix @ point.co), handle_left=list(matrix @ point.handle_left),
                handle_right=list(matrix @ point.handle_right), sample_id=str(uuid4()),
                handle_left_type=point.handle_left_type, handle_right_type=point.handle_right_type)


def _sample_draft(rows, resolution, cyclic=False):
    if all(row['type'] == 'POLY' for row in rows): return [row['values'] for row in rows]
    counts = _draft_counts(rows, resolution - (0 if cyclic else 1))
    result = []
    for row, count in zip(rows, counts):
        values = row['values'] if row['type'] == 'POLY' else [p['co'] for p in free_curve.bezier(row['values'], int(count) + 1)]
        result.append(values)
    return result


def _draft_counts(rows, intervals):
    import numpy as np
    result = np.array([len(row['values']) - 1 for row in rows]); indices = [i for i, row in enumerate(rows) if row['type'] == 'BEZIER']
    extra = intervals - int(result.sum())
    if extra < 0: raise ValueError('Sampling resolution cannot retain every explicit knot and POLY point.')
    if indices: result[indices] += free_curve.allocation([_draft_length(rows[i]) for i in indices], extra + len(indices)) - 1
    return result


def _draft_length(row):
    import numpy as np
    points = row['values'] if row['type'] == 'POLY' else [k['co'] for k in row['values']]
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def _joined(root, fiber, session, rows):
    points, indices = [], []; opening = session['opening']
    for span, values in zip(session['spans'], rows):
        if any((Vector(values[i]) - Vector(opening[span[key]])).length > 1e-5 for i, key in ((0, 'first'), (-1, 'last'))):
            raise ValueError('Structural span endpoints must retain their shared attachment positions.')
        indices.append(len(points)); points.extend(values[:-1])
    if fiber.topology_mode != 'LOOP': indices.append(len(points)); points.append(rows[-1][-1])
    payload = _draft_payload(fiber, session['payload'], points, indices)
    return payload, points


def _draft_payload(fiber, previous, points, indices):
    payload = free_path.make(points, fiber.topology_mode, runtime.structure(fiber), indices,
                             occurrences=[row['occurrence_id'] for row in previous['structural']])
    for index, old, new in zip(indices, previous['structural'], payload['structural']):
        payload['samples'][index]['sample_id'] = old['sample_id']; new['sample_id'] = old['sample_id']
    return payload


def apply(root, scene, fiber):
    session = state(root, fiber)
    if session is None: raise ValueError('No path editing session.')
    if session['stale'] or session['fingerprint'] != fingerprint(root, scene, fiber):
        session['stale'] = True; save_state(root, fiber, session); raise ValueError('STALE_FREE_EDIT: Refresh or explicitly Rebase the draft.')
    rows = draft(root, fiber, session); sampled = _sample_draft(rows, fiber.free_sampling_resolution, fiber.topology_mode == 'LOOP')
    payload, points = _joined(root, fiber, session, sampled)
    if rows != session.get('initial_draft'):
        service.commit(root, scene, fiber, payload, points, fiber.free_path_revision, editing=True)
    cancel(root, fiber)
    return fiber


def cancel(root, fiber):
    session = state(root, fiber)
    if session:
        for obj in objects(session): _remove_object(obj)
        root.pop(PREFIX + fiber.id, None)


def _remove_object(obj):
    data = obj.data; bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0: bpy.data.curves.remove(data)


def convert_bezier(root, fiber):
    session = state(root, fiber)
    for span in session['spans']:
        obj = _span_object(session, span); old = obj.data.splines[0]
        if old.type == 'BEZIER': continue
        points = [Vector(p.co[:3]) for p in old.points]; obj.data.splines.clear()
        spline = obj.data.splines.new('BEZIER'); spline.bezier_points.add(len(points) - 1)
        for target, point in zip(spline.bezier_points, points):
            target.co = point; target.handle_left_type = target.handle_right_type = 'VECTOR'


def resample(root, fiber):
    session = state(root, fiber); rows = _sample_draft(draft(root, fiber), fiber.free_sampling_resolution, fiber.topology_mode == 'LOOP')
    payload, points = _joined(root, fiber, session, rows)
    points, indices = free_curve.resample_spans(points, free_path.tagged_indices(payload), fiber.free_sampling_resolution, fiber.topology_mode == 'LOOP')
    spans = list(free_path.spans(points, indices, fiber.topology_mode == 'LOOP'))
    for span, indices in zip(session['spans'], spans):
        obj = _span_object(session, span); inverse = obj.matrix_world.inverted()
        _poly(obj.data, [inverse @ Vector(point) for point in points[indices]])


def refresh(root, scene, fiber, rebase=False):
    old = state(root, fiber); saved = draft(root, fiber, old)
    payload, current = runtime.current(root, scene, fiber)
    if runtime.structure(fiber) != tuple((r['point_id'], r['role']) for r in old['payload']['structural']):
        raise ValueError('Structural order changed; preserve the draft and Cancel before rebuilding.')
    sampled = _sample_draft(saved, fiber.free_sampling_resolution, fiber.topology_mode == 'LOOP') if rebase else None
    cancel(root, fiber); open_edit(root, scene, fiber); new = state(root, fiber)
    new['recovery'] = old.get('recovery', []) + [dict(spans=saved, opening=old['opening'], fingerprint=old['fingerprint'])]
    if rebase: _rebase_objects(root, old, new, sampled, current)
    save_state(root, fiber, new)
    return objects(new)


def _rebase_objects(root, old, new, sampled, current):
    for prior, span, row in zip(old['spans'], new['spans'], sampled):
        opening = _slice(old['opening'], prior); updated = _slice(current, span)
        values = free_path.rebase_span(opening, row, updated)
        obj = _span_object(new, span); inverse = obj.matrix_world.inverted()
        _poly(obj.data, [inverse @ Vector(p) for p in values])


def _slice(points, span):
    stop = span['last'] if span['last'] > span['first'] else span['last'] + len(points)
    return [points[i % len(points)] for i in range(span['first'], stop + 1)]


def restore_draft(root, scene, fiber, session):
    for obj in objects(session): _remove_object(obj)
    old_spans = session['spans']; session['spans'] = []
    for span, row in zip(old_spans, session.get('draft', session['initial_draft'])):
        values = row['values'] if row['type'] == 'POLY' else [k['co'] for k in row['values']]
        created = _new_span(root, scene, session, values, span['first'], span['last'])
        session['spans'].append(created)
        _restore_span(_span_object(session, created), row)
    session['stale'] = True; save_state(root, fiber, session)


def _restore_span(obj, row):
    obj.matrix_world = Matrix(row.get('matrix', obj.matrix_world))
    if row['type'] == 'BEZIER': _restore_bezier(obj, row['values'])
    else: _poly(obj.data, [obj.matrix_world.inverted() @ Vector(p) for p in row['values']])


def _restore_bezier(obj, knots):
    inverse = obj.matrix_world.inverted(); obj.data.splines.clear()
    spline = obj.data.splines.new('BEZIER'); spline.bezier_points.add(len(knots) - 1)
    for point, row in zip(spline.bezier_points, knots):
        point.co = inverse @ Vector(row['co']); point.handle_left_type = point.handle_right_type = 'FREE'
        point.handle_left = inverse @ Vector(row['handle_left']); point.handle_right = inverse @ Vector(row['handle_right'])
        point.handle_left_type = row.get('handle_left_type', 'FREE'); point.handle_right_type = row.get('handle_right_type', 'FREE')

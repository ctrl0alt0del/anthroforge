"""Selected-muscle A/B direction labels, without extra scene objects."""
import json
import bpy
from mathutils import Vector
_HANDLER = None
_CONTEXT_PROVIDER = None


def register(context_provider):
    global _HANDLER, _CONTEXT_PROVIDER
    _CONTEXT_PROVIDER = context_provider
    if not bpy.app.background and _HANDLER is None:
        _HANDLER = bpy.types.SpaceView3D.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    global _HANDLER
    if _HANDLER is not None: bpy.types.SpaceView3D.draw_handler_remove(_HANDLER, 'WINDOW')
    _HANDLER = None


def selected(context):
    from ...app.queries.vcp import active_muscle_from_context
    muscle = active_muscle_from_context(context)
    if muscle is None or muscle.envelope_sides != 'BOTH_SIDES': return ()
    if not context.space_data.overlay.show_overlays: return ()
    obj = next((o for o in context.scene.objects if o.get('af_muscle_id') == muscle.id and
                o.get('af_root_name') == muscle.id_data.name and o.get('af_muscle_surface') == 'INFL'
                and not o.get('af_muscle_mirror_proxy')), None)
    return json.loads(obj.get('af_envelope_arrows', '[]')) if obj and obj.visible_get() else ()


def draw():
    from bpy_extras.view3d_utils import location_3d_to_region_2d
    context = _CONTEXT_PROVIDER() if _CONTEXT_PROVIDER else None
    if context is None or not context.region_data: return
    for index, row in enumerate(selected(context)):
        points = [location_3d_to_region_2d(context.region, context.region_data, Vector(p)) for p in row]
        if all(p is not None for p in points): _arrow(points, 'A' if index == 0 else 'B', index)


def _arrow(points, label, index):
    import gpu, blf
    from gpu_extras.batch import batch_for_shader
    a, b = points; delta = b-a
    if delta.length < 1: return
    direction = delta.normalized(); cross = Vector((-direction.y, direction.x))
    lines = [a, b, b, b-direction*8+cross*4, b, b-direction*8-cross*4]
    color = (.2, .85, 1., 1.) if index == 0 else (1., .6, .15, 1.)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR'); shader.bind(); shader.uniform_float('color', color)
    batch_for_shader(shader, 'LINES', {'pos': lines}).draw(shader)
    blf.position(0, b.x+5, b.y+5, 0); blf.size(0, 16); blf.color(0, *color); blf.draw(0, label)


def arrows(work, result):
    import numpy as np
    from .muscle_envelope_storage import selected_settings
    if result.side_a is None or not len(result.base_vertices): return []
    _, _, part = selected_settings(work.muscle.id_data, work.muscle)
    faces = result.faces if result.face_parts is None else result.faces[result.face_parts == part]
    if not len(faces): return []
    ids = np.unique(faces); base = result.base_vertices
    displacement = result.side_a-result.side_b
    index = ids[np.argmax(np.linalg.norm(displacement[ids], axis=1))]
    direction = displacement[index]; length = np.linalg.norm(direction)
    if length < 1e-12: return []
    delta = direction/length * np.linalg.norm(np.ptp(base[ids], axis=0))*.18
    return [[base[index].tolist(), (base[index]+sign*delta).tolist()] for sign in (1, -1)]

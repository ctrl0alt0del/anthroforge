"""Publish independently evaluated mirror curves and expose actual consumer rows."""
import json
from mathutils import Matrix, Vector
from ..vcp.attachment_surface import muscle_backed
from ..vcp.fiber_instance import MirroredFiber
from ..vcp.fiber_support_validation import validate
from .muscle_fiber_attachment import resolve_batch
from .mirror_objects import ensure_private_data
from .fiber_sync_helpers import show_curve_preview


def update(root, scene, fiber, mirror):
    if not muscle_backed(fiber): return False
    try:
        view = MirroredFiber(fiber); rows, errors = resolve_batch(root, scene, (view,))
        if errors: raise ValueError(errors[fiber.id])
        points = rows[fiber.id]
        if not validate(root, scene, view, points): return _unsafe(root, scene, fiber, mirror)
        publish(mirror, fiber, points)
    except (ValueError, RuntimeError) as error:
        mirror['af_fiber_output_state'] = 'STALE'; mirror['af_attachment_error'] = str(error)
    return True


def _unsafe(root, scene, fiber, mirror):
    from ..vcp.free_path import is_free
    from .muscle_fiber_attachment import _unsafe as reroute
    mirror['af_fiber_output_state'] = 'STALE'
    mirror['af_attachment_error'] = 'Mirrored route collides with a selected support.'
    if not is_free(fiber): reroute(root, scene, MirroredFiber(fiber, True))
    return True


def apply_points(root, scene, fiber, points, commit):
    from .fiber_refinement import _find_proxy
    mirror = _find_proxy(scene, root.name, fiber.source.id + '@mirror')
    if mirror is None: raise ValueError('Mirrored Fiber output is missing.')
    if commit: publish(mirror, fiber, points)
    else: mirror['af_fiber_output_state'] = 'STALE'
    return mirror


def publish(mirror, fiber, points):
    ensure_private_data(mirror); mirror.matrix_world = Matrix.Identity(4)
    show_curve_preview(mirror, points, fiber.thickness, cyclic=fiber.topology_mode == 'LOOP')
    mirror['af_fiber_points_world'] = json.dumps([list(point) for point in points])
    mirror['af_fiber_output_state'] = 'CURRENT'; mirror['af_independent_surface_instance'] = True
    mirror.pop('af_attachment_error', None)


def actual_rows(root, scene, fiber):
    mirrors = [o for o in scene.objects if o.get('af_root_name') == root.name
               and o.get('af_fiber_mirror_proxy') and o.get('af_source_fiber_id') == fiber.id]
    if not muscle_backed(fiber): return None
    if len(mirrors) != 1 or mirrors[0].get('af_fiber_output_state') != 'CURRENT':
        raise ValueError(f'Mirrored instance of {fiber.id} is pending or invalid.')
    return [Vector(row) for row in json.loads(mirrors[0].get('af_fiber_points_world', '[]'))]

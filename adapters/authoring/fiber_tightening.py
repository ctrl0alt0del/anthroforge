"""Capture current Free geometry and native colliders for an unpublished edit."""
import numpy as np
from ...core.vcp.attachment_backend import attachment_runtime
from ...core.vcp.attachment_surface import support_keys
from ...core.vcp.fiber_pin_snapping import snap_request
from ...core.vcp.free_path import is_free, tagged_indices
from ...core.vcp.v3.tightening import tighten
from ...core.visualization import free_fiber_runtime as runtime
from ...core.authoring.errors import require


def preview(root, scene, fiber, params):
    require(is_free(fiber), 'FIBER_NOT_FREE', 'Freeze the committed Controlled path before tightening.')
    require(not root.get('af_free_edit_' + fiber.id), 'EDIT_IN_PROGRESS')
    context = attachment_runtime(scene); context['supports'] = support_keys(fiber)
    payload, points = runtime.current(root, scene, fiber, context)
    request = snap_request(root, scene, context, fiber.collision_radius)
    owners = [b['parent_id'] for b in runtime.bindings(fiber)]
    result, report = tighten(request, points, tagged_indices(payload), owners,
        accepted_steps=params.get('accepted_steps', 1), max_displacement=params['max_displacement'],
        cyclic=fiber.topology_mode == 'LOOP')
    return dict(fiber_id=fiber.id, fiber_name=fiber.name, path_revision=fiber.free_path_revision,
        path=path_input(payload, result), points_before=np.asarray(points).tolist(), tightening=report,
        accepted_steps_per_span=params.get('accepted_steps', 1), displacement_limit=params['max_displacement'],
        units='world_scene', dependent_surfaces='not_evaluated', mirrored_collision='not_evaluated')


def path_input(payload, points):
    samples = [dict(sample_id=row['sample_id'], co=list(map(float, point))) for row, point in zip(payload['samples'], points)]
    return dict(space='WORLD', representation='POLY', samples=samples, structural=payload['structural'])

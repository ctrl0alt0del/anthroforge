"""Publication state shared by attachment consumers and asynchronous producers."""
from ..vcp.surface_target import SurfaceRole


def generation(obj):
    from ..utils import deformation_generation
    return (int(obj.get('af_surface_generation', 0)), deformation_generation(obj),
            deformation_generation(obj.data), tuple(float(v) for row in obj.matrix_world for v in row))


def state(root, scene, ref, obj):
    if obj is None: return 'INVALID', 'Attachment surface is missing.'
    value = obj.get('af_muscle_output_state', 'CURRENT')
    if value != 'CURRENT': return value, 'Parent muscle geometry is not current.'
    if ref.surface != SurfaceRole.MUSCLE_INFL: return 'CURRENT', ''
    return _stacking_state(root, scene, ref, obj)


def _stacking_state(root, scene, ref, obj):
    from ..muscle_pairs import runtime
    from ..deps.surface_dependencies import stacking_targets
    if (ref.entity_id, ref.instance) not in stacking_targets(root): return 'CURRENT', ''
    entry = runtime.COORDINATOR.entries.get(runtime.key(scene, root))
    if entry and int(obj.get('af_stack_generation', -1)) == entry.generation: return 'CURRENT', ''
    status = 'not_scanned' if entry is None else entry.result.status
    if status in ('failed', 'unavailable', 'cancelled', 'incomplete'):
        return 'INVALID', 'Parent stacking publication failed; inspect Muscle relationships and recompute.'
    return 'PENDING', 'Waiting for final parent stacking publication.'


def require_current(root, scene, ref, obj):
    status, reason = state(root, scene, ref, obj)
    if status != 'CURRENT': raise ValueError(reason)


def changed(obj):
    obj['af_surface_generation'] = int(obj.get('af_surface_generation', 0)) + 1

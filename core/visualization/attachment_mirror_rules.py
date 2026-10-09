"""Resolve inherited symmetry through acyclic surface parent chains."""
from ..vcp.attachment_surface import muscle_backed
from ..vcp.fiber_modes import fiber_parent_ids
from ..vcp.surface_reference import reference, is_muscle


def inherited_rule(fiber, scps):
    targets = fiber_parent_ids(fiber)
    if any(reference(value).instance == 'mirror' for value in targets if is_muscle(value)): return None
    root = getattr(fiber, 'id_data', None)
    if root is None: return None
    rules = {_parent_rule(root, value, scps) for value in targets}
    if len(rules) > 1: raise ValueError('Attachment parents use incompatible symmetry rules. Choose an explicit symmetry setting.')
    return next(iter(rules), None)


def _parent_rule(root, value, scps):
    from .mirror_rules import _muscle_surface_source, effective_rule_for_muscle, effective_rule_for_scp
    from ..scp_runtime.common import attachment_dependency_id
    if not is_muscle(value): return effective_rule_for_scp(attachment_dependency_id(root, value), scps)
    muscles = {m.id: m for m in root.af_vcp_system.muscles}
    muscle = muscles.get(reference(value).entity_id)
    if muscle is None or _muscle_surface_source(muscle).use_mirrored_rows: return None
    return effective_rule_for_muscle(muscle, {f.id: f for f in root.af_vcp_system.fibers}, scps)


def for_fiber(fiber, scps):
    from .mirror_rules import authored_mirror_rule
    if fiber.get('af_authoring_symmetry') == 'explicit': return None
    return authored_mirror_rule(fiber) or inherited_rule(fiber, scps)

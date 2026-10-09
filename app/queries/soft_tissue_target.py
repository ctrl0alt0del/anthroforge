"""Human-readable target choices; keep proxy names out of tissue authoring."""
from .fiber_attachment import surface_choices
from .root import root_for_context
from .scp import scp_label
from ...core.vcp.surface_reference import reference, from_object


def target_label(root, ref):
    if ref.kind.value == 'NONE': return 'Choose target surface'
    if ref.kind.value == 'SCP': return f'{scp_label(root, ref.entity_id)} / SCP surface'
    muscle = next((m for m in root.af_vcp_system.muscles if m.id == ref.entity_id), None)
    name = muscle.name if muscle is not None else ref.entity_id + ' (missing)'
    role = 'Inflated surface' if ref.surface.value == 'MUSCLE_INFL' else 'Base surface'
    return f'{name} / {role}'


def target_description(ref):
    if ref.surface.value == 'MUSCLE_INFL': return 'Follows muscle inflation and stacking. Use this for tissue on a muscle.'
    if ref.surface.value == 'MUSCLE_BASE': return 'Follows the muscle base before inflation; inflation changes do not move this target.'
    return 'Follows the SCP geometry.'


def target_choices(root, scene):
    rows = []
    for value, _label, _description in surface_choices(root, scene):
        ref = reference(value)
        if ref.instance == 'source': rows.append((value, target_label(root, ref), target_description(ref)))
    return rows + [('NONE', 'No target', 'Clear the target surface selection')]


def picker_label(context):
    root = root_for_context(context)
    obj = getattr(context.scene, 'af_new_soft_tissue_target_obj', None)
    return target_label(root, from_object(obj)) if root is not None and obj is not None else 'Choose target surface'


def creation_uses_fibers(context):
    root, obj = root_for_context(context), getattr(context, 'active_object', None)
    return bool(root and obj and obj.get('af_root_name') == root.name
                and (obj.get('af_fiber_proxy') or obj.get('af_fiber_surface_proxy')))

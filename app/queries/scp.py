try:
    from ...core.selection import get_active_scp
    from ...core.vcp.surface_reference import is_typed, reference
except ImportError:
    from core.selection import get_active_scp
    from core.vcp.surface_reference import is_typed, reference

from .root import root_for_context


def active_scp_from_context(context):
    root = root_for_context(context)
    return None if root is None else get_active_scp(root, context)


def active_scp_id(context):
    scp = active_scp_from_context(context)
    return "" if scp is None else str(getattr(scp, "id", "") or "")


def scp_label(root, scp_id):
    if is_typed(scp_id): return _surface_label(root, scp_id)
    if not scp_id:
        return "-"
    for scp in root.af_scp_system.scps:
        if scp.id == scp_id:
            return scp.name if getattr(scp, "name", "") else scp.id
    return f"{scp_id} (missing)"


def _surface_label(root, value):
    ref = reference(value)
    records = root.af_vcp_system.muscles if ref.kind.value == 'MUSCLE' else root.af_scp_system.scps
    item = next((m for m in records if m.id == ref.entity_id), None)
    name = ref.entity_id + ' (missing)' if item is None else item.name
    return f'{name} / {ref.surface.value.removeprefix("MUSCLE_")} / {ref.instance}'

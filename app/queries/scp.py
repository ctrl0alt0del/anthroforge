try:
    from ...core.selection import get_active_scp
except ImportError:
    from core.selection import get_active_scp

from .root import root_for_context


def active_scp_from_context(context):
    root = root_for_context(context)
    return None if root is None else get_active_scp(root, context)


def active_scp_id(context):
    scp = active_scp_from_context(context)
    return "" if scp is None else str(getattr(scp, "id", "") or "")


def scp_label(root, scp_id):
    if not scp_id:
        return "-"
    for scp in root.af_scp_system.scps:
        if scp.id == scp_id:
            return scp.name if getattr(scp, "name", "") else scp.id
    return f"{scp_id} (missing)"

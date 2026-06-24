from dataclasses import dataclass

try:
    from ...core.scp_proxy import active_session, proxy_notice, session_owner_id
except ImportError:
    from core.scp_proxy import active_session, proxy_notice, session_owner_id

from .root import root_for_context
from .scp import active_scp_from_context, scp_label


@dataclass(frozen=True)
class ProxyViewPanelState:
    can_switch: bool = False
    can_exit: bool = False
    active_name: str = ""
    message: str = ""


def proxy_view_panel_state(context):
    root = root_for_context(context)
    scp = active_scp_from_context(context)
    session = {} if root is None else active_session(root)
    owner_id = "" if root is None else session_owner_id(root)
    active_name = "" if not owner_id else scp_label(root, owner_id)
    return ProxyViewPanelState(bool(scp), bool(session), active_name, _message(root, scp, session, active_name))


def _message(root, scp, session, active_name):
    if root is None:
        return "No AF_ROOT found."
    if session:
        return f"Proxy view active: {active_name}." if active_name else "Proxy view session is active."
    if proxy_notice(root):
        return proxy_notice(root)
    if scp is None:
        return "Select an SCP or one of its bound objects."
    return "Build original and mirrored proxies for the active SCP subtree."

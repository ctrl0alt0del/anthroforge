from dataclasses import dataclass

try:
    from ...core.scp_proxy import active_session, selected_proxy_vertices
except ImportError:
    from core.scp_proxy import active_session, selected_proxy_vertices

from .root import root_for_context


@dataclass(frozen=True)
class ProxyFiberCreateState:
    can_connect: bool = False
    message: str = ""


def proxy_fiber_create_state(context):
    root = root_for_context(context)
    if root is None:
        return ProxyFiberCreateState(False, "No AF_ROOT found.")
    if not active_session(root):
        return ProxyFiberCreateState(False, "Switch to proxy view first.")
    picks, error = selected_proxy_vertices(context)
    return ProxyFiberCreateState(not error and len(tuple(picks or ())) == 2, error or "Create a fiber from selected proxy vertices.")

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
    return _proxy_state(picks, error)


def loop_fiber_create_state(context):
    root = root_for_context(context)
    if root is None:
        return ProxyFiberCreateState(False, "No AF_ROOT found.")
    if _proxy_target(context):
        return _loop_proxy_state(context, root)
    if _mesh_target(context, root.name):
        return _loop_mesh_state(context)
    return ProxyFiberCreateState(False, "Edit one geometry mesh or switch to proxy view.")


def _proxy_state(picks, error):
    if error:
        return ProxyFiberCreateState(False, error)
    enough = len(tuple(picks or ())) >= 2
    return ProxyFiberCreateState(enough, "Connect selected proxy vertices with a fiber." if enough else "Select at least two proxy vertices.")


def _loop_proxy_state(context, root):
    _ = root
    picks, error = selected_proxy_vertices(context)
    return _count_state(picks, error, 3, "Create a loop fiber from the ordered proxy vertices.")


def _loop_mesh_state(context):
    return _count_state(_selected_mesh_indices(context), "", 3, "Create a loop fiber from the ordered mesh vertices.")


def _count_state(items, error, minimum, message):
    if error:
        return ProxyFiberCreateState(False, error)
    enough = len(tuple(items or ())) >= int(minimum)
    return ProxyFiberCreateState(enough, message if enough else f"Select at least {minimum} ordered vertices.")


def _proxy_target(context):
    obj = getattr(context, "active_object", None)
    return bool(getattr(context, "mode", "") == "EDIT_MESH" and obj and obj.get("af_scp_proxy_view"))


def _mesh_target(context, root_name):
    obj = getattr(context, "active_object", None)
    valid = getattr(context, "mode", "") == "EDIT_MESH" and len(tuple(getattr(context, "objects_in_mode", ()) or (obj,))) == 1
    return bool(valid and _is_geometry_scp_obj()(obj, root_name))


def _selected_mesh_indices(context):
    import bmesh

    bm = bmesh.from_edit_mesh(context.active_object.data)
    bm.verts.ensure_lookup_table()
    history = [elem.index for elem in bm.select_history if isinstance(elem, bmesh.types.BMVert) and elem.select]
    seen = set(history)
    return history + [vert.index for vert in bm.verts if vert.select and vert.index not in seen]


def _is_geometry_scp_obj():
    try:
        from ...core.scp_runtime.common import is_geometry_scp_obj
    except ImportError:
        from core.scp_runtime.common import is_geometry_scp_obj
    return is_geometry_scp_obj

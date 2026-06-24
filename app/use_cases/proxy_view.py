import bpy

from .results import failure, success

try:
    from ..queries.root import root_for_context
    from ..queries.scp import active_scp_from_context
    from ...core.scp_proxy import activate_session, active_session, build_proxy_view, clear_proxy_notice, deactivate_session
    from ...core.scp_proxy.visibility import hidden_scope_objects
    from ...core.scp_runtime.mirror_roles import apply_scp_mirror_roles
    from ...core.visualization.mirror_objects import remove_obj
except ImportError:
    from app.queries.root import root_for_context
    from app.queries.scp import active_scp_from_context
    from core.scp_proxy import activate_session, active_session, build_proxy_view, clear_proxy_notice, deactivate_session
    from core.scp_proxy.visibility import hidden_scope_objects
    from core.scp_runtime.mirror_roles import apply_scp_mirror_roles
    from core.visualization.mirror_objects import remove_obj


def switch_to_proxy_view(context):
    root = root_for_context(context)
    scp = active_scp_from_context(context)
    if root is None or scp is None:
        return failure("Select an active SCP first.")
    clear_proxy_notice(root)
    _ensure_object_mode(context)
    apply_scp_mirror_roles(root)
    build = build_proxy_view(root, context.scene, scp.id)
    return _activate_build(context, root, build)


def exit_proxy_view(context):
    root = root_for_context(context)
    if root is None:
        return failure("No AF_ROOT found.")
    _ensure_object_mode(context)
    if not active_session(root):
        return failure("No proxy view session is active.")
    deactivate_session(root, context.scene)
    clear_proxy_notice(root)
    return success("Exited proxy view.")


def _activate_build(context, root, build):
    if not build.ok:
        return failure(build.message, value=list(build.errors))
    try:
        _replace_session(root, context.scene, build)
        _select_proxy(context, build.original or build.mirrored)
        return success(build.message, value=build)
    except Exception as exc:
        _cleanup_build(build)
        return failure(str(exc))


def _replace_session(root, scene, build):
    if active_session(root):
        deactivate_session(root, scene)
    hidden = hidden_scope_objects(scene, root.name, build.payload["scp_ids"], build.payload["mirror_target_ids"])
    activate_session(root, scene, build.payload, hidden)


def _cleanup_build(build):
    for obj in (getattr(build, "original", None), getattr(build, "mirrored", None)):
        None if obj is None else remove_obj(obj)


def _select_proxy(context, obj):
    for item in tuple(getattr(context, "selected_objects", ()) or ()):
        item.select_set(False)
    if obj is not None:
        obj.select_set(True)
        context.view_layer.objects.active = obj


def _ensure_object_mode(context):
    if getattr(context, "mode", "") != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

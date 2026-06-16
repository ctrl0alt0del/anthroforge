def handle_attachment_toggle(context):
    scene = None if context is None else getattr(context, "scene", None)
    return _enable_attachments(scene) if _attachments_enabled(scene) else None


def _enable_attachments(scene):
    root = _get_root(scene)
    if root is None:
        return None
    _capture_authored()(root, scene)
    _sync_scene()(root=root, scene=scene, dirty_hints=_empty_hints()(), source="attachment_toggle", event_type="UPDATE")


def _attachments_enabled(scene):
    try:
        from ...core.scp_runtime.attachment_gate import attachments_enabled
    except ImportError:
        from core.scp_runtime.attachment_gate import attachments_enabled
    return attachments_enabled(scene)


def _capture_authored():
    try:
        from ...core.scp_runtime.attachment_runtime import capture_authored_scp_attachments
    except ImportError:
        from core.scp_runtime.attachment_runtime import capture_authored_scp_attachments
    return capture_authored_scp_attachments


def _empty_hints():
    try:
        from ...core.deps.dirty_hints import empty_dirty_hints
    except ImportError:
        from core.deps.dirty_hints import empty_dirty_hints
    return empty_dirty_hints


def _get_root(scene):
    try:
        from ...core.utils import get_af_root
    except ImportError:
        from core.utils import get_af_root
    return get_af_root(scene)


def _sync_scene():
    try:
        from ...app.runtime_api import sync_scene
    except ImportError:
        from app.runtime_api import sync_scene
    return sync_scene

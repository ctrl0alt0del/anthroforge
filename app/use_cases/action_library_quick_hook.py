from dataclasses import dataclass

import bpy

from ...core.action_library_quick_hook import (
    apply_quick_hook_settings,
    apply_reuse_target,
    build_quick_hook_draft,
    deselect_edit_points,
    next_hook_name,
    remember_quick_hook,
    reusable_quick_hook,
    supported_edit_object,
)
from ...core.deps.dirty_hints import dirty_hints_for
from ...core.scp_runtime.bound_objects import find_bound_entry_by_object, remove_bound_object, sync_scp_roles
from ...core.scp_runtime.common import scp_for_object
from ...core.scp_runtime.object_roles import add_bound_object_to_scp
from ...core.utils import get_af_root
from ...core.visualization.scp_control_helpers import mark_scp_control_object
from ..runtime_api import sync_context


@dataclass
class QuickHookArtifacts:
    geometry: object
    modifier: object = None
    control: object = None
    temporary: object = None
    bound_id: str = ""


def quick_hook_draft(context):
    root, scp, obj, error = _quick_hook_context(context)
    if error:
        return None, error
    reuse = _requested_reuse(context, obj, scp.id)
    draft = build_quick_hook_draft(obj, scp.id, reuse)
    error = "Select at least one editable point." if draft is None else ""
    return draft, error


def _quick_hook_context(context):
    scene = None if context is None else getattr(context, "scene", None)
    root = get_af_root(scene)
    obj = None if context is None else getattr(context, "active_object", None)
    if root is None:
        return root, None, obj, "Create or load an AnthroForge root first."
    error = _object_context_error(root, obj)
    scp = None if error else scp_for_object(root, obj)
    return root, scp, obj, error or ("Active object does not belong to an SCP." if scp is None else "")


def _object_context_error(root, obj):
    if not supported_edit_object(obj) or getattr(obj, "mode", "") != "EDIT":
        return "Use Edit Mode on an SCP-bound Mesh, Curve, Surface, or Lattice."
    if obj.get("af_scp_mirror"):
        return "Quick Hook is unavailable on generated mirrors."
    valid = obj.get("af_scp_bound") and obj.get("af_root_name") == root.name
    return "Active object must be bound to this SCP root." if not valid else ""


def _requested_reuse(context, obj, scp_id):
    scene = context.scene
    if not bool(getattr(scene, "af_action_quick_hook_reuse", False)):
        return None
    return reusable_quick_hook(scene, obj, scp_id)


def commit_quick_hook(context, draft):
    root, scp, obj, error = _quick_hook_context(context)
    if error or obj != draft.geometry or str(scp.id) != str(draft.scp_id):
        return False, error or "Quick Hook context changed before confirmation."
    error = _prepare_commit_draft(context, scp, draft)
    if error:
        return False, error
    return _commit_prepared(context, root, scp, draft)


def _commit_prepared(context, root, scp, draft):
    artifacts = QuickHookArtifacts(draft.geometry)
    try:
        _create_native_hook(artifacts)
        _finish_hook_data(root, scp, draft, artifacts)
        _finish_hook_context(context, root, scp, draft, artifacts)
        _remember_success(context, scp, draft, artifacts)
    except Exception as exc:
        _rollback_hook(root, scp, artifacts)
        return False, f"Quick Hook failed: {exc}"
    return True, ""


def _prepare_commit_draft(context, scp, draft):
    fresh = build_quick_hook_draft(draft.geometry, scp.id)
    if fresh is None:
        return "Select at least one editable point."
    live = None if draft.reuse is None else reusable_quick_hook(context.scene, draft.geometry, scp.id)
    valid = live and live.control == draft.reuse.control and live.modifier == draft.reuse.modifier
    if draft.reuse is not None and not valid:
        draft.reuse, draft.center = None, fresh.center
    return ""


def _create_native_hook(artifacts):
    objects = {_pointer(obj) for obj in bpy.data.objects}
    modifiers = {_pointer(mod) for mod in artifacts.geometry.modifiers}
    result = bpy.ops.object.hook_add_newob("EXEC_DEFAULT", False)
    if "FINISHED" not in result:
        raise RuntimeError("Blender could not create the native Hook")
    artifacts.modifier = _new_hook_modifier(artifacts.geometry, modifiers)
    artifacts.temporary = _new_empty(objects)
    if artifacts.modifier is None or artifacts.temporary is None:
        raise RuntimeError("Could not identify Blender's new Hook data")


def _new_hook_modifier(obj, before):
    rows = [mod for mod in obj.modifiers if mod.type == "HOOK" and _pointer(mod) not in before]
    return rows[0] if len(rows) == 1 else None


def _new_empty(before):
    rows = [obj for obj in bpy.data.objects if obj.type == "EMPTY" and _pointer(obj) not in before]
    return rows[0] if len(rows) == 1 else None


def _finish_hook_data(root, scp, draft, artifacts):
    apply_quick_hook_settings(artifacts.modifier, draft)
    if draft.reuse is not None:
        _finish_reused_hook(draft, artifacts)
    else:
        _finish_new_hook(root, scp, artifacts)


def _remember_success(context, scp, draft, artifacts):
    remember_quick_hook(context.scene, draft.geometry, scp.id, artifacts.control, artifacts.modifier)
    context.scene.af_action_quick_hook_reuse = True


def _finish_new_hook(root, scp, artifacts):
    control = artifacts.temporary
    control.name = next_hook_name(scp.name)
    artifacts.modifier.name = f"AF Hook {control.name}"
    if not add_bound_object_to_scp(root, scp, control):
        raise RuntimeError("Could not bind the new control to its SCP")
    artifacts.bound_id = find_bound_entry_by_object(scp, control).id
    sync_scp_roles(root, scp)
    artifacts.control = mark_scp_control_object(control, root, scp.id)


def _finish_reused_hook(draft, artifacts):
    artifacts.control = draft.reuse.control
    apply_reuse_target(artifacts.modifier, draft.reuse)
    artifacts.modifier.name = f"AF Hook {artifacts.control.name}"
    bpy.data.objects.remove(artifacts.temporary, do_unlink=True)
    artifacts.temporary = None


def _finish_hook_context(context, root, scp, draft, artifacts):
    deselect_edit_points(draft.geometry)
    context.view_layer.objects.active = draft.geometry
    draft.geometry.select_set(True)
    hints = dirty_hints_for("SCP", {str(scp.id)})
    sync_context(context, dirty_hints=hints, source="operator", event_type="UPDATE")


def _rollback_hook(root, scp, artifacts):
    _rollback_bound(root, scp, artifacts.bound_id)
    _rollback_modifier(artifacts.geometry, artifacts.modifier)
    owned = artifacts.control if artifacts.bound_id else None
    for obj in {artifacts.temporary, owned}:
        _rollback_object(obj)


def _rollback_bound(root, scp, bound_id):
    if not bound_id:
        return
    try:
        remove_bound_object(root, scp, bound_id)
    except Exception:
        pass
    indexes = [i for i, entry in enumerate(scp.bound_objects) if str(entry.id) == str(bound_id)]
    for index in reversed(indexes):
        scp.bound_objects.remove(index)


def _rollback_modifier(obj, modifier):
    try:
        if _is_live_modifier(obj, modifier):
            obj.modifiers.remove(modifier)
    except Exception:
        pass


def _rollback_object(obj):
    try:
        if _is_live_object(obj):
            bpy.data.objects.remove(obj, do_unlink=True)
    except Exception:
        pass


def _is_live_modifier(obj, modifier):
    try:
        return modifier is not None and obj.modifiers.get(modifier.name) == modifier
    except ReferenceError:
        return False


def _is_live_object(obj):
    try:
        return obj is not None and bpy.data.objects.get(obj.name) == obj
    except ReferenceError:
        return False


def _pointer(value):
    try:
        return int(value.as_pointer())
    except Exception:
        return id(value)

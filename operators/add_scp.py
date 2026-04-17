import bpy

from ..core.utils import get_af_root
from ..core.id_utils import next_prefixed_id
from ..core.deps.dirty_hints import dirty_hints_for
from ..core.visualization.sync_runner import sync_from_dirty_hints


def _is_marked_source_scp(obj, root_name):
    return bool(
        obj
        and obj.type == "MESH"
        and obj.get("af_scp")
        and not obj.get("af_scp_mirror")
        and obj.get("af_root_name") == root_name
        and obj.get("af_scp_id")
    )


def _find_scp_by_id(root, scp_id):
    for scp in root.af_scp_system.scps:
        if scp.id == scp_id:
            return scp
    return None


def _find_scp_by_object_name(root, object_name):
    for scp in root.af_scp_system.scps:
        if str(getattr(scp, "object_name", "") or "") == str(object_name or ""):
            return scp
    return None


def _find_scp_index(root, scp_id):
    for i, scp in enumerate(root.af_scp_system.scps):
        if scp.id == scp_id:
            return i
    return -1


def _effective_parent_obj(scene, root):
    parent_candidate = getattr(scene, "af_scp_parent_obj", None)
    if _is_marked_source_scp(parent_candidate, root.name):
        return parent_candidate
    return None


def _would_create_parent_cycle(root, child_scp_id, parent_scp_id):
    child_id = str(child_scp_id or "")
    parent_id = str(parent_scp_id or "")
    if not child_id or not parent_id:
        return False
    if child_id == parent_id:
        return True

    by_id = {str(s.id): s for s in root.af_scp_system.scps}
    cur = parent_id
    seen = set()
    while cur and cur not in seen:
        if cur == child_id:
            return True
        seen.add(cur)
        scp = by_id.get(cur)
        if scp is None:
            return False
        cur = str(getattr(scp, "parent_id", "") or "")
    return False


def _clear_native_parent_keep_world(child_obj):
    if child_obj is None:
        return
    if getattr(child_obj, "parent", None) is None:
        return
    world = child_obj.matrix_world.copy()
    child_obj.parent = None
    child_obj.matrix_world = world


def _set_parent_relation(child_obj, child_scp, parent_obj):
    _clear_native_parent_keep_world(child_obj)

    if parent_obj is None:
        child_scp.parent_id = ""
        return

    child_scp.parent_id = str(parent_obj.get("af_scp_id") or "")


class AF_OT_AddSCP(bpy.types.Operator):
    bl_idname = "af.add_scp"
    bl_label = "Mark Selected Mesh As SCP"
    bl_description = "Mark active mesh object as SCP"

    def _ensure_marked_tags(self, obj, root_name, scp_id):
        obj["af_scp"] = True
        obj["af_root_name"] = root_name
        obj["af_scp_id"] = scp_id

    def _ensure_collection_entry(self, root, obj):
        existing_id = str(obj.get("af_scp_id") or "")
        existing = _find_scp_by_id(root, existing_id) if existing_id else None
        if existing is None:
            existing = _find_scp_by_object_name(root, obj.name)

        if existing is None:
            scp = root.af_scp_system.scps.add()
            scp.id = next_prefixed_id(root.af_scp_system.scps, "SCP")
            scp.name = obj.name
            scp.object_name = obj.name
            scp.parent_id = ""
            scp.mirror_enabled = False
            scp.mirror_axis = "X"
            scp.mirror_origin = (0.0, 0.0, 0.0)
            scp.mirror_status = "NONE"
            scp.mirror_source_id = ""
            scp.mirror_effective_axis = "X"
            return scp, True

        existing.name = obj.name
        existing.object_name = obj.name
        return existing, False

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            self.report({"ERROR"}, "No AF_ROOT found in scene.")
            return {"CANCELLED"}

        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "Select a mesh object first.")
            return {"CANCELLED"}

        if obj.get("af_scp_mirror"):
            self.report({"ERROR"}, "Cannot mark mirror object as SCP.")
            return {"CANCELLED"}

        scp, is_new = self._ensure_collection_entry(root, obj)
        self._ensure_marked_tags(obj, root.name, scp.id)

        parent_obj = _effective_parent_obj(context.scene, root)
        if parent_obj is not None:
            parent_id = str(parent_obj.get("af_scp_id") or "")
            if _would_create_parent_cycle(root, scp.id, parent_id):
                self.report({"ERROR"}, "Parent relation would create a cycle.")
                return {"CANCELLED"}
            _set_parent_relation(obj, scp, parent_obj)
        elif is_new:
            _set_parent_relation(obj, scp, None)
        else:
            _clear_native_parent_keep_world(obj)

        idx = _find_scp_index(root, scp.id)
        if idx >= 0:
            root.af_scp_system.active_scp_index = idx

        sync_from_dirty_hints(
            root=root,
            scene=context.scene,
            dirty_hints=dirty_hints_for("SCP", {scp.id}),
            source="operator",
            event_type="MARK",
        )
        self.report({"INFO"}, f"Marked '{obj.name}' as {scp.id}")
        return {"FINISHED"}


class AF_OT_SetSCPParent(bpy.types.Operator):
    bl_idname = "af.set_scp_parent"
    bl_label = "Set SCP Parent"
    bl_description = "Assign or clear parent for active SCP"

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return {"CANCELLED"}

        child_obj = context.active_object
        if not _is_marked_source_scp(child_obj, root.name):
            self.report({"ERROR"}, "Active object must be a marked SCP mesh.")
            return {"CANCELLED"}

        child_id = str(child_obj.get("af_scp_id") or "")
        child_scp = _find_scp_by_id(root, child_id)
        if child_scp is None:
            self.report({"ERROR"}, "Active SCP entry not found.")
            return {"CANCELLED"}

        parent_obj = getattr(context.scene, "af_scp_parent_obj", None)
        parent_id = ""
        if parent_obj is not None:
            if not _is_marked_source_scp(parent_obj, root.name):
                self.report({"ERROR"}, "Parent must be another marked SCP mesh.")
                return {"CANCELLED"}
            parent_id = str(parent_obj.get("af_scp_id") or "")
            if _would_create_parent_cycle(root, child_id, parent_id):
                self.report({"ERROR"}, "Parent relation would create a cycle.")
                return {"CANCELLED"}

        _set_parent_relation(child_obj, child_scp, parent_obj)

        sync_from_dirty_hints(
            root=root,
            scene=context.scene,
            dirty_hints=dirty_hints_for("SCP", {child_id}),
            source="operator",
            event_type="UPDATE",
        )
        return {"FINISHED"}

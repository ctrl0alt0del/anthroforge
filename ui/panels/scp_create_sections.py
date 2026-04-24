from ...core.utils import get_af_root


def is_marked_scp_obj(obj):
    return bool(obj and obj.get("af_scp") and not obj.get("af_scp_mirror") and obj.get("af_scp_id"))


def active_scp_prop(root, obj):
    if root is None or obj is None:
        return None
    sid = str(obj.get("af_scp_id") or "")
    return next((scp for scp in root.af_scp_system.scps if str(getattr(scp, "id", "") or "") == sid), None)


def draw_active_object_box(layout, obj):
    box = layout.box()
    box.label(text="Mark Existing Mesh As SCP")
    if obj is None:
        box.label(text="No active object", icon="INFO")
        return
    box.label(text=f"Active: {obj.name}")
    box.label(text=f"Type: {obj.type}")


def draw_mark_button(layout):
    layout.row(align=True).operator("af.add_scp", icon="ADD", text="Mark Selected Mesh")


def draw_delete_button(layout, obj):
    _ = obj
    layout.operator("af.unmark_scp", icon="TRASH", text="Unmark Selected SCP")


def draw_parent_box(layout, scene, scp):
    box = layout.box()
    box.label(text="Parent Relation")
    box.prop(scene, "af_scp_parent_obj", text="Parent")
    box.operator("af.set_scp_parent", text="Apply Parent", icon="CONSTRAINT")
    if scp is not None and str(getattr(scp, "parent_id", "") or ""):
        box.prop(scp, "attach_follow_rotation", text="Follow Rotation")


def draw_mirror_box(layout, scp):
    box = layout.box()
    box.label(text="Mirror")
    box.prop(scp, "mirror_enabled", text="Mirror Children")
    axis_row = box.row()
    axis_row.enabled = bool(scp.mirror_enabled)
    axis_row.prop(scp, "mirror_axis", text="Axis")

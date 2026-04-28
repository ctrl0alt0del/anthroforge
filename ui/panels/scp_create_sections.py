from ...core.scp_runtime.common import scp_for_object


def is_marked_scp_obj(obj):
    return bool(obj and obj.get("af_scp_bound") and not obj.get("af_scp_mirror") and obj.get("af_scp_id"))


def active_scp_prop(root, obj):
    return None if root is None or obj is None else scp_for_object(root, obj)


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


def draw_parent_box(layout, scene, scp):
    box = layout.box()
    box.label(text="Parent Relation")
    box.prop(scene, "af_scp_parent_obj", text="Parent")
    box.operator("af.set_scp_parent", text="Apply Parent", icon="CONSTRAINT")
    draw_attachment_settings(box, scp)


def draw_attachment_settings(layout, scp):
    if scp is None or not str(getattr(scp, "parent_id", "") or ""):
        return
    layout.prop(scp, "attach_child_anchor_mode", text="Child Anchor")
    layout.prop(scp, "attach_follow_rotation", text="Follow Rotation")


def draw_mirror_box(layout, scp):
    box = layout.box()
    box.label(text="Mirror")
    box.prop(scp, "mirror_enabled", text="Mirror Children")
    axis_row = box.row()
    axis_row.enabled = bool(scp.mirror_enabled)
    axis_row.prop(scp, "mirror_axis", text="Axis")

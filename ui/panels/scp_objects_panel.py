def _role_text(scp, entry):
    obj = getattr(entry, "object_ref", None)
    roles = []
    roles += ["Transform"] if obj == getattr(scp, "transform_object_ref", None) else []
    roles += ["Geometry"] if obj == getattr(scp, "geometry_object_ref", None) else []
    return ", ".join(roles) if roles else "Bound"


def _draw_role_value(box, label, obj):
    row = box.row()
    row.label(text=label)
    row.label(text="" if obj is None else obj.name)


def _draw_bound_row(box, scp, entry):
    obj = getattr(entry, "object_ref", None)
    row = box.row(align=True)
    row.label(text="" if obj is None else obj.name)
    row.label(text=_role_text(scp, entry))
    if obj != getattr(scp, "transform_object_ref", None):
        op = row.operator("af.remove_scp_bound_object", text="", icon="X")
        op.bound_id = entry.id


def _draw_bound_list(layout, scp):
    box = layout.box()
    box.label(text="Bound Objects")
    for entry in scp.bound_objects:
        _draw_bound_row(box, scp, entry)


def _draw_picker(layout, scene):
    box = layout.box()
    box.label(text="Object Roles")
    box.prop(scene, "af_scp_object_picker", text="Object")
    row = box.row(align=True)
    row.operator("af.set_scp_transform_object", text="Set as Transform")
    row.operator("af.set_scp_geometry_object", text="Set as Geometry")
    box.operator("af.add_scp_bound_object", text="Add to Bound Objects")

def draw_scp_object_section(layout, scene, scp):
    roles = layout.box()
    _draw_role_value(roles, "Transform", getattr(scp, "transform_object_ref", None))
    _draw_role_value(roles, "Geometry", getattr(scp, "geometry_object_ref", None))
    _draw_picker(layout, scene)
    _draw_bound_list(layout, scp)

import bpy

try:
    from ...core.draft_skin.constants import COLLAGEN_GROUP
    from ...core.draft_skin.settings import effective_collagen
except ImportError:
    from core.draft_skin.constants import COLLAGEN_GROUP
    from core.draft_skin.settings import effective_collagen


def source_object(scp):
    obj = None if scp is None else getattr(scp, "geometry_object_ref", None)
    if obj is None or obj.type != "MESH":
        raise ValueError("The active SCP has no mesh geometry.")
    return obj


def effective_scp_value(scp, obj=None):
    obj = source_object(scp) if obj is None else obj
    return effective_collagen(scp.skin_collagen_mode, scp.skin_collagen, scp.name, obj.name)


def prepare_paint(context, scp):
    obj = source_object(scp)
    _object_mode(context)
    value = effective_scp_value(scp, obj)
    if scp.skin_collagen_mode == "AUTO":
        scp.skin_collagen = value
    group = ensure_group(obj, value)
    scp.skin_collagen_mode = "PAINTED"
    _activate(context, obj, group)
    set_brush_weight(context, value)
    bpy.ops.object.mode_set(mode="WEIGHT_PAINT")
    return obj


def ensure_group(obj, fallback):
    group = obj.vertex_groups.get(COLLAGEN_GROUP) or obj.vertex_groups.new(name=COLLAGEN_GROUP)
    missing = _unassigned_vertices(obj, group.index)
    if missing:
        group.add(missing, float(fallback), "REPLACE")
    return group


def _unassigned_vertices(obj, group_index):
    return [
        vertex.index for vertex in obj.data.vertices
        if not any(item.group == group_index for item in vertex.groups)
    ]


def fill_default(context, scp):
    obj = source_object(scp)
    was_painting = context.object == obj and obj.mode == "WEIGHT_PAINT"
    _object_mode(context)
    group = obj.vertex_groups.get(COLLAGEN_GROUP) or obj.vertex_groups.new(name=COLLAGEN_GROUP)
    group.add(list(range(len(obj.data.vertices))), float(scp.skin_collagen), "REPLACE")
    scp.skin_collagen_mode = "PAINTED"
    if was_painting:
        _activate(context, obj, group)
        bpy.ops.object.mode_set(mode="WEIGHT_PAINT")
    return group


def clear_map(context, scp):
    obj = source_object(scp)
    _object_mode(context)
    group = obj.vertex_groups.get(COLLAGEN_GROUP)
    if group is not None:
        obj.vertex_groups.remove(group)
    scp.skin_collagen_mode = "UNIFORM"


def finish_paint(context, scp):
    obj = source_object(scp)
    if context.object == obj and obj.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def set_brush_weight(context, value):
    unified = context.scene.tool_settings.weight_paint.unified_paint_settings
    unified.use_unified_weight = True
    unified.weight = min(1.0, max(0.0, float(value)))


def _object_mode(context):
    if context.object is not None and context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def _activate(context, obj, group):
    for item in tuple(context.selected_objects):
        item.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    obj.vertex_groups.active_index = group.index

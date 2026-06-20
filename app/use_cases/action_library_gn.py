import bpy

try:
    from ...core.action_library_curve_loft import build_curve_loft_group
except ImportError:
    from core.action_library_curve_loft import build_curve_loft_group


def create_curve_loft_group(context, overwrite=False):
    name = _group_name(context)
    count = _curve_count(context)
    single_angle = _single_angle(context)
    group = _existing_group(name)
    error = _create_error(name, count, group, overwrite)
    if error:
        return False, error
    _build_group(name, count, single_angle, group, overwrite)
    return True, ""


def _group_name(context):
    scene = getattr(context, "scene", None)
    return str(getattr(scene, "af_action_gn_name", "") or "").strip()


def _curve_count(context):
    scene = getattr(context, "scene", None)
    return int(getattr(scene, "af_action_curve_count", 0) or 0)


def _single_angle(context):
    scene = getattr(context, "scene", None)
    return bool(getattr(scene, "af_action_single_angle", False))


def curve_loft_exists(context):
    return _existing_group(_group_name(context)) is not None


def curve_loft_name(context):
    return _group_name(context)


def _existing_group(name):
    return bpy.data.node_groups.get(name) if name else None


def _build_group(name, count, single_angle, group, overwrite):
    if group and overwrite:
        return _replace_group(group, name, count, single_angle)
    return build_curve_loft_group(name, count, single_angle=single_angle)


def _modifier_snapshot(group):
    return [(mod, _socket_snapshot(group, mod)) for obj in bpy.data.objects for mod in obj.modifiers if _uses_group(mod, group)]


def _uses_group(mod, group):
    return str(getattr(mod, "type", "")) == "NODES" and getattr(mod, "node_group", None) == group


def _socket_snapshot(group, mod):
    return {sock.name: _socket_payload(mod, sock.identifier) for sock in _input_sockets(group) if sock.identifier in mod}


def _input_sockets(group):
    items = tuple(group.interface.items_tree)
    return [item for item in items if getattr(item, "item_type", "") == "SOCKET" and getattr(item, "in_out", "") == "INPUT"]


def _socket_payload(mod, identifier):
    return mod[identifier], mod.get(f"{identifier}_use_attribute"), mod.get(f"{identifier}_attribute_name")


def _restore_modifier_snapshot(snapshot, group):
    ids = {sock.name: sock.identifier for sock in _input_sockets(group)}
    for mod, values in snapshot:
        mod.node_group = None
        mod.node_group = group
        _restore_modifier_values(mod, ids, values)


def _restore_modifier_values(mod, ids, values):
    for name, identifier in ids.items():
        payload = _restore_payload(name, values)
        if payload is not None:
            _restore_modifier_value(mod, identifier, payload)


def _restore_payload(name, values):
    payload = values.get(name)
    return payload if payload is not None else _angle_payload(name, values)


def _angle_payload(name, values):
    if name == "Angle":
        return _first_payload(values, "Angle", "Angle 01", "Lower Angle")
    if name == "Angle 01":
        return _first_payload(values, "Angle 01", "Lower Angle", "Angle")
    return _first_payload(values, name, "Angle") if name.startswith("Angle ") else None


def _first_payload(values, *names):
    for name in names:
        if name in values:
            return values[name]
    return None


def _restore_modifier_value(mod, identifier, payload):
    value, use_attr, attr_name = payload
    mod[identifier] = value
    _restore_socket_flag(mod, f"{identifier}_use_attribute", use_attr)
    _restore_socket_flag(mod, f"{identifier}_attribute_name", attr_name)


def _restore_socket_flag(mod, key, value):
    if value is None and key not in mod:
        return
    mod[key] = bool(value) if key.endswith("_use_attribute") else value


def _replace_group(group, name, count, single_angle):
    snapshot = _modifier_snapshot(group)
    group.name = f"{name}__OLD__"
    new_group = build_curve_loft_group(name, count, single_angle=single_angle)
    _restore_modifier_snapshot(snapshot, new_group)
    _discard_group(group)
    return new_group


def _discard_group(group):
    if getattr(group, "users", 0) == 0:
        bpy.data.node_groups.remove(group)


def _create_error(name, count, group, overwrite):
    if not name:
        return "Enter a node group name."
    if count < 2:
        return "Curve count must be at least 2."
    if group and str(getattr(group, "bl_idname", "")) != "GeometryNodeTree":
        return f'Node group "{name}" exists but is not a Geometry Nodes group.'
    return f'Node group "{name}" already exists.' if group and not overwrite else ""

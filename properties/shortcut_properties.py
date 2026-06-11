import bpy

from ..core.shortcuts import child_override_items, parent_override_items

_VEC_SIZE = 32
_FALSES = (False,) * _VEC_SIZE
_ZEROES = (0,) * _VEC_SIZE
_FLOATS = (0.0,) * _VEC_SIZE


def _edit_api():
    try:
        from ..app.use_cases import shortcut_edit
    except ImportError:
        from app.use_cases import shortcut_edit
    return shortcut_edit


def _ctx():
    return getattr(bpy, "context", None)


def _proxy_enum_items(self, _context):
    return _edit_api().live_shortcut_enum_items(_ctx(), self)


def _live_value(shortcut):
    return _edit_api().live_shortcut_value(_ctx(), shortcut)


def _live_array(shortcut, caster=float):
    return _edit_api().live_shortcut_array(_ctx(), shortcut, _VEC_SIZE, caster=caster)


def _set_value(shortcut, value):
    return _edit_api().apply_shortcut_value(_ctx(), shortcut, value)


def _bool_get(self):
    return bool(_live_value(self))


def _bool_set(self, value):
    _set_value(self, bool(value))


def _int_get(self):
    return int(_live_value(self) or 0)


def _int_set(self, value):
    _set_value(self, int(value))


def _float_get(self):
    return float(_live_value(self) or 0.0)


def _float_set(self, value):
    _set_value(self, float(value))


def _string_get(self):
    return str(_live_value(self) or "")


def _string_set(self, value):
    _set_value(self, str(value or ""))


def _enum_get(self):
    return str(_live_value(self) or "NONE")


def _enum_set(self, value):
    _set_value(self, str(value or "NONE"))


def _bool_vec_get(self):
    return _live_array(self, caster=bool)


def _bool_vec_set(self, value):
    _set_value(self, tuple(bool(v) for v in tuple(value or ())))


def _int_vec_get(self):
    return _live_array(self, caster=int)


def _int_vec_set(self, value):
    _set_value(self, tuple(int(v) for v in tuple(value or ())))


def _float_vec_get(self):
    return _live_array(self, caster=float)


def _float_vec_set(self, value):
    _set_value(self, tuple(float(v) for v in tuple(value or ())))


class AF_DataShortcutOverride_Property(bpy.types.PropertyGroup):
    target_scp_id: bpy.props.StringProperty(name="Target SCP", default="")
    parent_anchor_mode: bpy.props.EnumProperty(name="Parent Anchor", items=parent_override_items(), default="KEEP")
    child_anchor_mode: bpy.props.EnumProperty(name="Child Anchor", items=child_override_items(), default="KEEP")


class AF_DataShortcut_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="ID")
    name: bpy.props.StringProperty(name="Name", default="Shortcut")
    owner_type: bpy.props.StringProperty(name="Owner Type", default="NONE")
    owner_id: bpy.props.StringProperty(name="Owner ID", default="")
    data_path: bpy.props.StringProperty(name="Data Path", default="")
    overrides: bpy.props.CollectionProperty(type=AF_DataShortcutOverride_Property)
    proxy_sync_lock: bpy.props.BoolProperty(default=False, options={"SKIP_SAVE"})
    proxy_bool: bpy.props.BoolProperty(get=_bool_get, set=_bool_set, options={"SKIP_SAVE"})
    proxy_int: bpy.props.IntProperty(get=_int_get, set=_int_set, options={"SKIP_SAVE"})
    proxy_float: bpy.props.FloatProperty(get=_float_get, set=_float_set, options={"SKIP_SAVE"})
    proxy_string: bpy.props.StringProperty(get=_string_get, set=_string_set, options={"SKIP_SAVE"})
    proxy_enum: bpy.props.EnumProperty(items=_proxy_enum_items, get=_enum_get, set=_enum_set, options={"SKIP_SAVE"})
    proxy_bool_vec: bpy.props.BoolVectorProperty(size=_VEC_SIZE, default=_FALSES, get=_bool_vec_get, set=_bool_vec_set, options={"SKIP_SAVE"})
    proxy_int_vec: bpy.props.IntVectorProperty(size=_VEC_SIZE, default=_ZEROES, get=_int_vec_get, set=_int_vec_set, options={"SKIP_SAVE"})
    proxy_float_vec: bpy.props.FloatVectorProperty(size=_VEC_SIZE, default=_FLOATS, get=_float_vec_get, set=_float_vec_set, options={"SKIP_SAVE"})


class AF_DataShortcut_System_Property(bpy.types.PropertyGroup):
    shortcuts: bpy.props.CollectionProperty(type=AF_DataShortcut_Property)
    active_shortcut_index: bpy.props.IntProperty(default=-1)

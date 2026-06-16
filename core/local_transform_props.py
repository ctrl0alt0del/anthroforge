from dataclasses import dataclass

from mathutils import Vector

from .utils import scene_for_id, update_scene_view_layer

_AXES = ("X", "Y", "Z")
_KEYS = tuple(f"AF Local {axis}" for axis in _AXES)
_VARS = ("afx", "afy", "afz")
_UNIT_AXES = tuple(Vector(values) for values in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))


@dataclass(frozen=True)
class LocalTransformState:
    installed: bool = False
    has_props: bool = False
    has_conflict: bool = False
    message: str = ""


def local_transform_keys():
    return _KEYS


def local_transform_state(obj):
    props = _has_props(obj)
    drivers = _has_local_drivers(obj)
    conflict = _has_location_drivers(obj) and not drivers
    return LocalTransformState(drivers and props, props, conflict, _state_message(obj, drivers and props, props, conflict))


def create_local_transform_props(obj):
    return _rebuild_props(obj, require_props=False)


def rebind_local_transform_props(obj):
    return _rebuild_props(obj, require_props=True)


def remove_local_transform_props(obj):
    error = _remove_error(obj)
    if error:
        return False, error
    location = obj.location.copy()
    _clear_local_drivers(obj)
    obj.location = location
    _clear_props(obj)
    _refresh_object(obj)
    return True, ""


def _rebuild_props(obj, require_props):
    error = _rebuild_error(obj, require_props)
    if error:
        return False, error
    base, axes = _capture_basis(obj)
    _ensure_props(obj)
    _set_prop_values(obj, 0.0)
    _clear_local_drivers(obj)
    _install_driver_set(obj, base, axes)
    _refresh_object(obj)
    return True, ""


def _rebuild_error(obj, require_props):
    if obj is None:
        return "Select an active object first."
    if _has_location_drivers(obj) and not _has_local_drivers(obj):
        return "Location already has non-Action-Library drivers."
    return "Create Local Transform Properties first." if require_props and not _has_props(obj) else ""


def _remove_error(obj):
    if obj is None:
        return "Select an active object first."
    if _has_location_drivers(obj) and not _has_local_drivers(obj):
        return "Location already has non-Action-Library drivers."
    return "" if _has_props(obj) or _has_local_drivers(obj) else "Local Transform Properties are not installed."


def _state_message(obj, installed, has_props, conflict):
    if obj is None:
        return "Select an object to create helper properties."
    if conflict:
        return "Location already uses other drivers."
    if installed:
        return "Drivers are installed. These properties are ready for shortcuts."
    return "Custom properties exist but drivers are missing." if has_props else "Create helper properties on the active object."


def _capture_basis(obj):
    mat = obj.matrix_basis.to_3x3()
    axes = tuple(_axis_column(mat, index) for index in range(3))
    return obj.location.copy(), axes


def _axis_column(matrix, index):
    axis = matrix.col[index].copy()
    return _UNIT_AXES[index].copy() if axis.length <= 1.0e-8 else axis.normalized()


def _ensure_props(obj):
    for axis, key in zip(_AXES, _KEYS):
        _ensure_prop(obj, axis, key)


def _ensure_prop(obj, axis, key):
    obj[key] = 0.0 if key not in obj else float(obj.get(key, 0.0) or 0.0)
    _configure_prop_ui(obj, axis, key)


def _configure_prop_ui(obj, axis, key):
    try:
        obj.id_properties_ui(key).update(description=f"Offset along captured local {axis} axis.", default=0.0, subtype="DISTANCE")
    except Exception:
        return


def _set_prop_values(obj, value):
    for key in _KEYS:
        obj[key] = float(value)


def _install_driver_set(obj, base, axes):
    for index in range(3):
        _install_driver(obj, index, float(base[index]), _driver_components(axes, index))


def _driver_components(axes, index):
    return tuple(float(axis[index]) for axis in axes)


def _install_driver(obj, index, base, comps):
    fcurve = obj.driver_add("location", index)
    driver = fcurve.driver
    driver.type = "SCRIPTED"
    _clear_driver_vars(driver)
    _add_driver_vars(driver, obj)
    driver.expression = _driver_expression(base, comps)


def _clear_driver_vars(driver):
    while driver.variables:
        driver.variables.remove(driver.variables[0])


def _add_driver_vars(driver, obj):
    for name, key in zip(_VARS, _KEYS):
        _add_driver_var(driver, obj, name, key)


def _add_driver_var(driver, obj, name, key):
    var = driver.variables.new()
    var.name = name
    var.targets[0].id = obj
    var.targets[0].data_path = _prop_path(key)


def _driver_expression(base, comps):
    parts = [f"({_num(base)})"]
    parts += [f"({_num(value)}*{name})" for value, name in zip(comps, _VARS)]
    return "+".join(parts)


def _num(value):
    return format(float(value), ".17g")


def _prop_path(key):
    return f'["{str(key or "")}"]'


def _has_props(obj):
    return bool(obj and all(key in obj for key in _KEYS))


def _has_location_drivers(obj):
    return any(_location_fcurves(obj))


def _has_local_drivers(obj):
    return all(_is_local_driver(_location_driver(obj, index), obj) for index in range(3))


def _location_driver(obj, index):
    return next((fc for fc in _location_fcurves(obj) if int(getattr(fc, "array_index", -1)) == index), None)


def _location_fcurves(obj):
    anim = getattr(obj, "animation_data", None)
    drivers = getattr(anim, "drivers", ()) if anim is not None else ()
    return tuple(fc for fc in tuple(drivers or ()) if str(getattr(fc, "data_path", "")) == "location")


def _is_local_driver(fcurve, obj):
    if fcurve is None or str(getattr(getattr(fcurve, "driver", None), "type", "")) != "SCRIPTED":
        return False
    return len(getattr(fcurve.driver, "variables", ())) == 3 and all(_matches_var(fcurve.driver, obj, name, key) for name, key in zip(_VARS, _KEYS))


def _matches_var(driver, obj, name, key):
    var = next((item for item in tuple(driver.variables or ()) if str(getattr(item, "name", "")) == name), None)
    target = None if var is None else var.targets[0]
    return bool(target and target.id == obj and str(getattr(target, "data_path", "")) == _prop_path(key))


def _clear_local_drivers(obj):
    if not _has_local_drivers(obj):
        return
    for index in range(3):
        obj.driver_remove("location", index)


def _clear_props(obj):
    for key in _KEYS:
        if key in obj:
            del obj[key]


def _refresh_object(obj):
    obj.update_tag()
    update_scene_view_layer(scene_for_id(obj))

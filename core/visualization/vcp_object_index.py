def _as_id(value):
    return str(value or "")


def build_vcp_object_index(vis_col, root_name, *, first_match=False):
    index = _empty_index()
    objects = tuple(getattr(vis_col, "objects", ()) or ())
    # Mirror synchronization historically selected the first matching object.
    for obj in reversed(objects) if first_match else objects:
        if _as_id(obj.get("af_root_name")) == _as_id(root_name):
            _index_obj(index, obj)
    return index


def build_muscle_object_index(scene, root_name):
    import bpy
    index = build_vcp_object_index(scene, root_name)
    for obj in bpy.data.objects:
        if obj.get('af_muscle_inflation_ctrl') and obj.get('af_root_name') == root_name:
            index['inflation'].setdefault(_as_id(obj.get('af_muscle_id')), obj)
    index['_global_inflation'] = True
    return index


def remember_object(index, obj):
    if index is not None: _index_obj(index, obj)
    return obj


def forget_object(index, obj):
    for bucket in (index or {}).values():
        if not isinstance(bucket, dict): continue
        for key, value in tuple(bucket.items()):
            if value is obj: del bucket[key]


def _empty_index():
    return {"fiber": {}, "fiber_surface": {}, "endpoint": {}, "touch": {}, "loop": {}, "muscle": {}, "inflation": {}, "fiber_mirror": {}, "muscle_mirror": {}}


def _index_obj(index, obj):
    _index_fiber(index, obj)
    _index_fiber_surface(index, obj)
    _index_fiber_handles(index, obj)
    _index_muscle(index, obj)


def _index_fiber_surface(index, obj):
    if obj.get("af_fiber_surface_proxy"):
        index["fiber_surface"][_as_id(obj.get("af_fiber_surface_id"))] = obj


def _index_fiber(index, obj):
    if obj.get("af_fiber_proxy") and not obj.get("af_fiber_mirror_proxy"):
        index["fiber"][_as_id(obj.get("af_fiber_id"))] = obj
    if obj.get("af_fiber_proxy") and obj.get("af_fiber_mirror_proxy"):
        index["fiber_mirror"][_as_id(obj.get("af_source_fiber_id"))] = obj


def _index_fiber_handles(index, obj):
    fid = _as_id(obj.get("af_fiber_id"))
    if obj.get("af_fiber_endpoint_handle"):
        index["endpoint"][(fid, _as_id(obj.get("af_fiber_endpoint")))] = obj
    if obj.get("af_fiber_touch_handle"):
        index["touch"][(fid, int(obj.get("af_fiber_touch_index", -1)))] = obj
    if obj.get("af_fiber_loop_anchor_handle"):
        index["loop"][(fid, int(obj.get("af_fiber_loop_anchor_index", -1)))] = obj


def _index_muscle(index, obj):
    mid, surf = _as_id(obj.get("af_muscle_id")), _as_id(obj.get("af_muscle_surface"))
    if obj.get("af_muscle_proxy") and not obj.get("af_muscle_mirror_proxy"):
        index["muscle"][(mid, surf)] = obj
    if obj.get("af_muscle_proxy") and obj.get("af_muscle_mirror_proxy"):
        index["muscle_mirror"][(_as_id(obj.get("af_source_muscle_id")), surf)] = obj
    if obj.get("af_muscle_inflation_ctrl"):
        index["inflation"][mid] = obj

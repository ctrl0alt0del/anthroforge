def _as_id(value):
    return str(value or "")


def build_vcp_object_index(vis_col, root_name):
    index = _empty_index()
    for obj in tuple(getattr(vis_col, "objects", ()) or ()):
        if _as_id(obj.get("af_root_name")) == _as_id(root_name):
            _index_obj(index, obj)
    return index


def _empty_index():
    return {"fiber": {}, "endpoint": {}, "touch": {}, "loop": {}, "muscle": {}, "inflation": {}, "fiber_mirror": {}, "muscle_mirror": {}}


def _index_obj(index, obj):
    _index_fiber(index, obj)
    _index_fiber_handles(index, obj)
    _index_muscle(index, obj)


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

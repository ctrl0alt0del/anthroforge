import bpy
from bpy.app.handlers import persistent

from ..deps.controls import classify_control_object, is_control_object
from ..deps.dirty_hints import dirty_hints_for
from ..scp_runtime.common import is_bound_scp_obj
from ..utils import get_af_root


ENTITY_TYPES = ("SCP", "FIBER", "MUSCLE", "BLOB")


def _active_object():
    try:
        ctx = bpy.context
        if ctx is None or ctx.view_layer is None:
            return None
        return ctx.view_layer.objects.active
    except Exception:
        return None


def _entity_from_active_object(root):
    obj = _active_object()
    if obj is None or obj.get("af_root_name") != root.name:
        return "NONE", ""
    if is_bound_scp_obj(obj, root.name):
        return "SCP", str(obj.get("af_scp_id"))
    return _entity_from_control(obj) or _entity_from_proxy(obj) or ("NONE", "")


def _entity_from_control(obj):
    hints = dict((classify_control_object(obj) or {}).get("dirty_hints", {}) or {})
    for et in ENTITY_TYPES:
        vals = set(hints.get(et, set()) or set())
        if vals:
            return et, str(next(iter(vals)))
    return None


def _entity_from_proxy(obj):
    checks = (("af_fiber_proxy", "af_fiber_id", "FIBER"), ("af_muscle_proxy", "af_muscle_id", "MUSCLE"), ("af_blob_proxy", "af_blob_id", "BLOB"))
    for flag, id_key, kind in checks:
        if obj.get(flag) and obj.get(id_key):
            return kind, str(obj.get(id_key))
    return None


def _scp_index(root, scp_id):
    sid = str(scp_id or "")
    for index, scp in enumerate(root.af_scp_system.scps):
        if str(getattr(scp, "id", "") or "") == sid:
            return index
    return -1


def _set_active_scp_index(root, scene, index):
    if int(getattr(root.af_scp_system, "active_scp_index", -1)) == int(index):
        return
    scene.af_selection_sync_lock = True
    try:
        root.af_scp_system.active_scp_index = int(index)
    finally:
        scene.af_selection_sync_lock = False


def _sync_active_scp_state(root, scene, entity):
    if entity[0] == "SCP":
        _set_active_scp_index(root, scene, _scp_index(root, entity[1]))


def _active_scp_entity(root):
    idx = int(getattr(root.af_scp_system, "active_scp_index", -1))
    if 0 <= idx < len(root.af_scp_system.scps):
        sid = str(root.af_scp_system.scps[idx].id or "")
        if sid:
            return "SCP", sid
    return None


def _active_vcp_entity(root):
    vcp = root.af_vcp_system
    vtype = str(getattr(vcp, "active_vcp_type", "NONE") or "NONE")
    vid = str(getattr(vcp, "active_vcp_id", "") or "")
    return (vtype, vid) if vtype in ENTITY_TYPES[1:] and vid else None


def resolve_active_entity(root):
    direct = _entity_from_active_object(root)
    if direct[0] != "NONE":
        return direct
    return _active_scp_entity(root) or _active_vcp_entity(root) or ("NONE", "")


def active_entity_id(root, entity_type):
    et = str(entity_type or "").upper()
    cur_type, cur_id = resolve_active_entity(root)
    if cur_type == et and cur_id:
        return cur_id
    return ""


def _remove_transient_controls():
    for obj in list(bpy.data.objects):
        if not is_control_object(obj):
            continue
        data = getattr(obj, "data", None)
        bpy.data.objects.remove(obj, do_unlink=True)
        if data and getattr(data, "users", 0) == 0:
            try:
                if isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)
                elif isinstance(data, bpy.types.Curve):
                    bpy.data.curves.remove(data)
            except Exception:
                pass


def _hints_for_switch(prev_entity, curr_entity):
    dirty = _switch_dirty(prev_entity, curr_entity)
    return {} if not dirty else _merge_switch_hints(dirty)


def _switch_dirty(prev_entity, curr_entity):
    dirty = {}
    for et, eid in (prev_entity, curr_entity):
        if et in ENTITY_TYPES and eid:
            dirty.setdefault(et, set()).add(str(eid))
    return dirty


def _merge_switch_hints(dirty):
    hints = {}
    for et, ids in dirty.items():
        _merge_hints(hints, dirty_hints_for(et, ids))
    return hints


def _merge_hints(target, source):
    for key, vals in source.items():
        target.setdefault(key, set())
        target[key] |= set(vals or set())


def _sync_from_hints(root, scene, hints):
    from .sync_runner import sync_from_dirty_hints
    sync_from_dirty_hints(
        root=root,
        scene=scene,
        dirty_hints=hints,
        source="depsgraph",
        event_type="SELECTION",
    )


class ControlRuntimeOrchestrator:
    def __init__(self):
        self._last_active = ("NONE", "")
        self._syncing = False

    def reset(self):
        self._last_active = ("NONE", "")

    def _sync_for_scene(self, scene, prev_entity, curr_entity):
        root = get_af_root(scene)
        hints = _hints_for_switch(prev_entity, curr_entity)
        if root is not None and hints:
            _sync_from_hints(root, scene, hints)

    def on_depsgraph_update(self, scene, depsgraph):
        _depsgraph = depsgraph
        if self._syncing:
            return
        self.sync_now(scene, force=False)

    def sync_now(self, scene, force=False):
        if self._syncing:
            return
        state = self._sync_state(scene, force)
        if state is None:
            return
        prev, current = state
        self._syncing = True
        try:
            self._sync_for_scene(scene, prev, current)
        finally:
            self._syncing = False

    def _clear_last_active(self):
        self._last_active = ("NONE", "")

    def _sync_state(self, scene, force):
        root, current = _root_and_current(scene)
        if root is None:
            self._clear_last_active()
            return None
        _sync_active_scp_state(root, scene, current)
        if not force and current == self._last_active:
            return None
        prev = self._last_active
        self._last_active = current
        return prev, current


_CONTROL_RUNTIME = None


@persistent
def _on_save_pre(_dummy):
    _remove_transient_controls()


@persistent
def _on_load_post(_dummy):
    _remove_transient_controls()
    if _CONTROL_RUNTIME is not None:
        _CONTROL_RUNTIME.reset()
    scene = getattr(bpy.context, "scene", None)
    root, current = _root_and_current(scene)
    if root is None:
        return
    _hydrate_load_state(root, scene, current)


def _root_and_current(scene):
    root = get_af_root(scene)
    return root, ("NONE", "") if root is None else resolve_active_entity(root)


def _hydrate_load_state(root, scene, current):
    _sync_active_scp_state(root, scene, current)


def register_control_runtime():
    global _CONTROL_RUNTIME
    if _CONTROL_RUNTIME is None:
        _CONTROL_RUNTIME = ControlRuntimeOrchestrator()
    if _CONTROL_RUNTIME.on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_CONTROL_RUNTIME.on_depsgraph_update)
    if _on_save_pre not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(_on_save_pre)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    return _CONTROL_RUNTIME


def notify_selection_changed(scene, force=False):
    runtime = register_control_runtime()
    runtime.sync_now(scene, force=bool(force))


def unregister_control_runtime():
    global _CONTROL_RUNTIME
    if _CONTROL_RUNTIME is None:
        return
    if _CONTROL_RUNTIME.on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_CONTROL_RUNTIME.on_depsgraph_update)
    if _on_save_pre in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(_on_save_pre)
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    _CONTROL_RUNTIME = None

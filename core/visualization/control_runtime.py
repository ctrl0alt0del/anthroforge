import bpy
from bpy.app.handlers import persistent

try:
    from ...app.runtime_api import sync_scene
    from ...app.context import selected_objects_for_scene
except ImportError:
    from app.runtime_api import sync_scene
    from app.context import selected_objects_for_scene
from ..deps.controls import classify_control_object, is_control_object
from ..deps.control_lifecycle import should_remove_control_object_on_load, should_remove_control_object_on_save
from ..deps.dirty_hints import dirty_hints_for, empty_dirty_hints
from ..scp_runtime.common import is_bound_scp_obj
from ..scp_runtime.prop_update_guard import suppress_scp_prop_updates
from ..scp_runtime.runtime_state import reset_scp_runtime_state
from ..shortcuts.owner_backsolve import retrofit_owner_backsolve_defaults
from ..shortcuts.session_state import reset_shortcut_runtime_state
from ..selection_order import update_selection_order
from ..utils import depsgraph_for_scene, get_af_root, view_layer_for_scene
from ..vcp.runtime_state import reset_vcp_runtime_state
from ..vcp.prop_update_guard import suppress_vcp_prop_updates


ENTITY_TYPES = ("SCP", "FIBER", "FIBER_SURFACE", "MUSCLE", "BLOB", "SOFT_TISSUE")
_HISTORY_SUSPENDED = False


def _active_object(scene, active_object=None):
    if active_object is not None:
        return active_object
    try:
        layer = view_layer_for_scene(scene)
        return None if layer is None else layer.objects.active
    except Exception:
        return None


def _entity_from_active_object(root, scene, active_object=None):
    obj = _active_object(scene, active_object)
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
    checks = (("af_fiber_proxy", "af_fiber_id", "FIBER"),
              ("af_fiber_surface_proxy", "af_fiber_surface_id", "FIBER_SURFACE"),
              ("af_muscle_proxy", "af_muscle_id", "MUSCLE"),
              ("af_blob_proxy", "af_blob_id", "BLOB"), ("af_soft_tissue_proxy", "af_soft_tissue_id", "SOFT_TISSUE"),
              ("af_soft_tissue_rest_proxy", "af_soft_tissue_id", "SOFT_TISSUE"),
              ("af_soft_tissue_base", "af_soft_tissue_id", "SOFT_TISSUE"))
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


def _sync_active_vcp_state(root, entity):
    if entity[0] not in ENTITY_TYPES[1:]:
        return
    vcp = root.af_vcp_system
    current = (str(vcp.active_vcp_type), str(vcp.active_vcp_id))
    if current != entity:
        vcp.active_vcp_type, vcp.active_vcp_id = entity


def _sync_active_entity_state(root, scene, entity):
    _sync_active_scp_state(root, scene, entity)
    _sync_active_vcp_state(root, entity)


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


def resolve_active_entity(root, scene=None, active_object=None):
    direct = _entity_from_active_object(root, scene, active_object)
    if direct[0] != "NONE":
        return direct
    return _active_scp_entity(root) or _active_vcp_entity(root) or ("NONE", "")


def active_entity_id(root, entity_type, scene=None, active_object=None):
    et = str(entity_type or "").upper()
    cur_type, cur_id = resolve_active_entity(root, scene, active_object)
    if cur_type == et and cur_id:
        return cur_id
    return ""


def _remove_transient_controls(should_remove_fn):
    for obj in bpy.data.objects:
        if not is_control_object(obj):
            continue
        if not should_remove_fn(obj):
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
    sync_scene(root=root, scene=scene, dirty_hints=hints, source="depsgraph", event_type="SELECTION")


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
        if self._syncing or _consume_history_suspend():
            return
        self.sync_now(scene, force=False)

    def sync_now(self, scene, force=False, active_object=None):
        if self._syncing:
            return
        state = self._sync_state(scene, force, active_object)
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

    def _sync_state(self, scene, force, active_object=None):
        update_selection_order(scene, selected_objects_for_scene(scene), active_object=active_object)
        root, current = _root_and_current(scene, active_object)
        if root is None:
            self._clear_last_active()
            return None
        _sync_active_entity_state(root, scene, current)
        if not force and current == self._last_active:
            return None
        prev = self._last_active
        self._last_active = current
        return prev, current


_CONTROL_RUNTIME = None


def _consume_history_suspend():
    global _HISTORY_SUSPENDED
    if not _HISTORY_SUSPENDED:
        return False
    _HISTORY_SUSPENDED = False
    return True


@persistent
def _on_history_pre(_dummy):
    global _HISTORY_SUSPENDED
    _HISTORY_SUSPENDED = True
    reset_shortcut_runtime_state()
    None if _CONTROL_RUNTIME is None else _CONTROL_RUNTIME.reset()


@persistent
def _on_save_pre(_dummy):
    _remove_transient_controls(should_remove_control_object_on_save)


@persistent
def _on_load_post(_dummy):
    reset_shortcut_runtime_state()
    _remove_transient_controls(should_remove_control_object_on_load)
    if _CONTROL_RUNTIME is not None:
        _CONTROL_RUNTIME.reset()
    for scene in bpy.data.scenes:
        for root in scene.objects:
            if root.get("anthroforge_root"):
                _hydrate_load_state(root, scene, resolve_active_entity(root, scene))


def _root_and_current(scene, active_object=None):
    root = get_af_root(scene)
    return root, ("NONE", "") if root is None else resolve_active_entity(root, scene, active_object)


def _load_scene():
    for scene in bpy.data.scenes:
        if get_af_root(scene) is not None:
            return scene
    return bpy.data.scenes[0] if bpy.data.scenes else None


def _hydrate_load_state(root, scene, current):
    retrofit_owner_backsolve_defaults(root)
    _sync_active_entity_state(root, scene, current)
    _hydrate_runtime_state(root, scene)
    _ensure_runtime_handlers()


def _prime_evaluated_depsgraph(scene):
    depsgraph_for_scene(scene)


def _hydrate_runtime_state(root, scene):
    reset_scp_runtime_state(root)
    reset_vcp_runtime_state(root)
    _prime_evaluated_depsgraph(scene)
    with suppress_scp_prop_updates(), suppress_vcp_prop_updates():
        sync_scene(root=root, scene=scene, dirty_hints=empty_dirty_hints(), source="load", event_type="LOAD")


def _ensure_runtime_handlers():
    from .sync import register_sync
    from .delete_reconcile import register_delete_reconcile
    register_sync()
    register_delete_reconcile()
    register_control_runtime()


def register_control_runtime():
    global _CONTROL_RUNTIME
    if _CONTROL_RUNTIME is None:
        _CONTROL_RUNTIME = ControlRuntimeOrchestrator()
    if _CONTROL_RUNTIME.on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_CONTROL_RUNTIME.on_depsgraph_update)
    if _on_history_pre not in bpy.app.handlers.undo_pre:
        bpy.app.handlers.undo_pre.append(_on_history_pre)
    if _on_history_pre not in bpy.app.handlers.redo_pre:
        bpy.app.handlers.redo_pre.append(_on_history_pre)
    if _on_save_pre not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(_on_save_pre)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    return _CONTROL_RUNTIME


def notify_selection_changed(scene, force=False, active_object=None):
    runtime = register_control_runtime()
    runtime.sync_now(scene, force=bool(force), active_object=active_object)


def unregister_control_runtime():
    global _CONTROL_RUNTIME
    if _CONTROL_RUNTIME is None:
        return
    if _CONTROL_RUNTIME.on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_CONTROL_RUNTIME.on_depsgraph_update)
    if _on_history_pre in bpy.app.handlers.redo_pre:
        bpy.app.handlers.redo_pre.remove(_on_history_pre)
    if _on_history_pre in bpy.app.handlers.undo_pre:
        bpy.app.handlers.undo_pre.remove(_on_history_pre)
    if _on_save_pre in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(_on_save_pre)
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    _CONTROL_RUNTIME = None

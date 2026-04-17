import bpy
from bpy.app.handlers import persistent

from ..deps.controls import classify_control_object, is_control_object
from ..deps.dirty_hints import dirty_hints_for
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

    if obj.get("af_scp") and not obj.get("af_scp_mirror") and obj.get("af_scp_id"):
        return "SCP", str(obj.get("af_scp_id"))

    c = classify_control_object(obj)
    if c:
        hints = dict(c.get("dirty_hints", {}) or {})
        for et in ENTITY_TYPES:
            vals = set(hints.get(et, set()) or set())
            if vals:
                return et, str(next(iter(vals)))

    checks = (
        ("af_fiber_proxy", "af_fiber_id", "FIBER"),
        ("af_muscle_proxy", "af_muscle_id", "MUSCLE"),
        ("af_blob_proxy", "af_blob_id", "BLOB"),
    )
    for flag, id_key, kind in checks:
        if obj.get(flag) and obj.get(id_key):
            return kind, str(obj.get(id_key))
    return "NONE", ""


def resolve_active_entity(root):
    direct = _entity_from_active_object(root)
    if direct[0] != "NONE":
        return direct

    idx = int(getattr(root.af_scp_system, "active_scp_index", -1))
    if 0 <= idx < len(root.af_scp_system.scps):
        sid = str(root.af_scp_system.scps[idx].id or "")
        if sid:
            return "SCP", sid

    vcp = root.af_vcp_system
    vtype = str(getattr(vcp, "active_vcp_type", "NONE") or "NONE")
    vid = str(getattr(vcp, "active_vcp_id", "") or "")
    if vtype in ("FIBER", "MUSCLE", "BLOB") and vid:
        return vtype, vid
    return "NONE", ""


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
    dirty = {}
    prev_type, prev_id = prev_entity
    curr_type, curr_id = curr_entity
    if prev_type in ENTITY_TYPES and prev_id:
        dirty.setdefault(prev_type, set()).add(str(prev_id))
    if curr_type in ENTITY_TYPES and curr_id:
        dirty.setdefault(curr_type, set()).add(str(curr_id))
    if not dirty:
        return {}

    hints = {}
    for et, ids in dirty.items():
        h = dirty_hints_for(et, ids)
        for k, vals in h.items():
            hints.setdefault(k, set())
            hints[k] |= set(vals or set())
    return hints


class ControlRuntimeOrchestrator:
    def __init__(self):
        self._last_active = ("NONE", "")
        self._syncing = False

    def reset(self):
        self._last_active = ("NONE", "")

    def _sync_for_scene(self, scene, prev_entity, curr_entity):
        root = get_af_root(scene)
        if root is None:
            return
        hints = _hints_for_switch(prev_entity, curr_entity)
        if not hints:
            return
        from .sync_runner import sync_from_dirty_hints

        sync_from_dirty_hints(
            root=root,
            scene=scene,
            dirty_hints=hints,
            source="depsgraph",
            event_type="SELECTION",
        )

    def on_depsgraph_update(self, scene, depsgraph):
        _depsgraph = depsgraph
        if self._syncing:
            return
        self.sync_now(scene, force=False)

    def sync_now(self, scene, force=False):
        if self._syncing:
            return
        root = get_af_root(scene)
        if root is None:
            self._last_active = ("NONE", "")
            return
        current = resolve_active_entity(root)
        if not force and current == self._last_active:
            return
        prev = self._last_active
        self._last_active = current
        self._syncing = True
        try:
            self._sync_for_scene(scene, prev, current)
        finally:
            self._syncing = False


_CONTROL_RUNTIME = None


@persistent
def _on_save_pre(_dummy):
    _remove_transient_controls()


@persistent
def _on_load_post(_dummy):
    _remove_transient_controls()
    if _CONTROL_RUNTIME is not None:
        _CONTROL_RUNTIME.reset()
    ctx = bpy.context
    scene = getattr(ctx, "scene", None)
    if scene is None:
        return
    root = get_af_root(scene)
    if root is None:
        return
    current = resolve_active_entity(root)
    if current[0] == "NONE":
        return
    from .sync_runner import sync_from_dirty_hints

    sync_from_dirty_hints(
        root=root,
        scene=scene,
        dirty_hints=_hints_for_switch(("NONE", ""), current),
        source="load_post",
        event_type="SELECTION",
    )


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

import bpy
from bpy.app.handlers import persistent

from ..deps.controls import classify_control_object, is_control_object
from ..deps.dirty_hints import dirty_hints_for
from ..utils import get_af_root
from .sync_runner import sync_from_dirty_hints


def _active_object():
    try:
        ctx = bpy.context
        if ctx is None or ctx.view_layer is None:
            return None
        return ctx.view_layer.objects.active
    except Exception:
        return None


def _entity_from_active(root):
    obj = _active_object()
    if obj is None or obj.get("af_root_name") != root.name:
        return "NONE", ""

    c = classify_control_object(obj)
    if c:
        hints = dict(c.get("dirty_hints", {}) or {})
        for et in ("FIBER", "MUSCLE", "BLOB"):
            vals = set(hints.get(et, set()) or set())
            if vals:
                return et, next(iter(vals))

    if obj.get("af_proxy") and obj.get("af_scp_id"):
        return "SCP", str(obj.get("af_scp_id"))
    if obj.get("af_fiber_proxy") and obj.get("af_fiber_id"):
        return "FIBER", str(obj.get("af_fiber_id"))
    if obj.get("af_muscle_proxy") and obj.get("af_muscle_id"):
        return "MUSCLE", str(obj.get("af_muscle_id"))
    if obj.get("af_blob_proxy") and obj.get("af_blob_id"):
        return "BLOB", str(obj.get("af_blob_id"))
    return "NONE", ""


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


class TransientControlRuntime:
    def __init__(self):
        self._last_active = ("NONE", "")
        self._syncing = False

    def reset(self):
        self._last_active = ("NONE", "")

    def on_depsgraph_update(self, scene, depsgraph):
        if self._syncing:
            return
        root = get_af_root(scene)
        if root is None:
            self._last_active = ("NONE", "")
            return

        current = _entity_from_active(root)
        if current == self._last_active:
            return
        prev = self._last_active
        self._last_active = current

        dirty = {}
        prev_type, prev_id = prev
        curr_type, curr_id = current
        if prev_type in ("FIBER", "MUSCLE", "BLOB") and prev_id:
            dirty.setdefault(prev_type, set()).add(prev_id)
        if curr_type in ("FIBER", "MUSCLE", "BLOB") and curr_id:
            dirty.setdefault(curr_type, set()).add(curr_id)
        if not dirty:
            return

        self._syncing = True
        try:
            hints = {}
            for et, ids in dirty.items():
                h = dirty_hints_for(et, ids)
                for k, vals in h.items():
                    hints.setdefault(k, set())
                    hints[k] |= set(vals or set())
            sync_from_dirty_hints(
                root=root,
                scene=scene,
                dirty_hints=hints,
                source="depsgraph",
                event_type="SELECTION",
            )
        finally:
            self._syncing = False


_TRANSIENT_CONTROL_RUNTIME = None


@persistent
def _on_save_pre(_dummy):
    _remove_transient_controls()


@persistent
def _on_load_post(_dummy):
    _remove_transient_controls()
    if _TRANSIENT_CONTROL_RUNTIME is not None:
        _TRANSIENT_CONTROL_RUNTIME.reset()


def register_transient_control_runtime():
    global _TRANSIENT_CONTROL_RUNTIME
    if _TRANSIENT_CONTROL_RUNTIME is None:
        _TRANSIENT_CONTROL_RUNTIME = TransientControlRuntime()

    if _TRANSIENT_CONTROL_RUNTIME.on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_TRANSIENT_CONTROL_RUNTIME.on_depsgraph_update)
    if _on_save_pre not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(_on_save_pre)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    return _TRANSIENT_CONTROL_RUNTIME


def unregister_transient_control_runtime():
    global _TRANSIENT_CONTROL_RUNTIME
    if _TRANSIENT_CONTROL_RUNTIME is None:
        return
    if _TRANSIENT_CONTROL_RUNTIME.on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_TRANSIENT_CONTROL_RUNTIME.on_depsgraph_update)
    if _on_save_pre in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(_on_save_pre)
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    _TRANSIENT_CONTROL_RUNTIME = None

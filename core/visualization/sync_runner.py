import bpy

from ..utils import get_af_root
from ..deps import run_dependency_runtime


_RUNNING = False
_PENDING = []
_TIMER_ARMED = False


def _run(root=None, scene=None, dirty_hints=None, bake=False, source="manual", event_type="UPDATE", payload=None):
    global _RUNNING
    if _RUNNING:
        return

    scene = scene or bpy.context.scene
    root = root or get_af_root(scene)
    if scene is None or root is None:
        return

    _RUNNING = True
    try:
        run_dependency_runtime(
            root=root,
            scene=scene,
            dirty_hints=dirty_hints,
            bake=bake,
            gate_meta={"source": source, "event_type": event_type, "payload": dict(payload or {})},
        )
    finally:
        _RUNNING = False


def _request(root, scene, dirty_hints, bake, source, event_type, payload):
    return {"root": root, "scene": scene, "dirty_hints": dirty_hints, "bake": bake, "source": source, "event_type": event_type, "payload": payload}


def _arm_timer():
    global _TIMER_ARMED
    if _TIMER_ARMED:
        return
    _TIMER_ARMED = True
    bpy.app.timers.register(_flush_pending, first_interval=0.0)


def _next_request():
    return None if not _PENDING else _PENDING.pop(0)


def _flush_pending():
    global _TIMER_ARMED
    request = _next_request()
    if request is None:
        _TIMER_ARMED = False
        return None
    _run(**request)
    return 0.0

def sync_from_dirty_hints(
    root=None, scene=None, dirty_hints=None, bake=False, source="manual", event_type="UPDATE", payload=None
):
    _run(
        root=root,
        scene=scene,
        dirty_hints=dirty_hints,
        bake=bake,
        source=source,
        event_type=event_type,
        payload=payload,
    )


def schedule_sync_from_dirty_hints(
    root=None, scene=None, dirty_hints=None, bake=False, source="manual", event_type="UPDATE", payload=None
):
    # Defer depsgraph-driven runtime work until Blender finishes the current evaluation pass.
    _PENDING.append(_request(root, scene, dirty_hints, bake, source, event_type, payload))
    _arm_timer()

"""Shared main-thread warning lifecycle; never calls sync, repair, planner or solver."""
import bpy
from bpy.app.handlers import persistent
from ..warnings import session
from ..warnings.anchors import identity, invalidate
from . import warning_capture as capture

_ENABLED = False
_TARGETS = {}
_MEMBERSHIPS = {}


class InvalidAnchorProvider:
    name = "fiber_hard_anchor.v1"

    def check_all(self, context):
        session.COORDINATOR.cancel_all()
        _TARGETS.clear()
        invalidate()
        session.REPOSITORY.discovery = "PENDING"
        session.REPOSITORY.changed()
        session.COORDINATOR.enqueue(discovery_scope(), discover)
        ensure_timer()

    def on_action(self, event, context):
        if str(event.get("event_type", "")).upper() == "SELECTION":
            return
        scene, root = context
        if scene is None or root is None:
            self.check_all(None)
            return
        dirty = event.get("dirty") or {}
        ids = None if event.get("full") or dirty.get("SCP") or not dirty else set(dirty.get("FIBER") or ())
        if ids is None or ids:
            schedule_root(scene, root, ids)
            session.COORDINATOR.metrics["incremental_checks"] += 1


def discovery_scope():
    return session.EPOCH, "", "", "FILE", "", 0


def root_scope(scene, root):
    return session.EPOCH, session.id_token(scene), session.id_token(root), "ROOT", "", 0


def discover(_token):
    live = set()
    for scene in bpy.data.scenes:
        for obj in scene.objects:
            if obj.get("anthroforge_root"):
                live.add((session.id_token(scene), session.id_token(obj)))
                schedule_root(scene, obj)
            yield
    for scope in tuple(session.REPOSITORY.states):
        if scope[3] != "FILE" and (scope[1], scope[2]) not in live:
            session.REPOSITORY.remove(scope)
    session.REPOSITORY.discovery = "COMPLETE"
    session.REPOSITORY.changed()


def schedule_root(scene, root, ids=None):
    key = root_scope(scene, root)
    prior = _TARGETS.get(key, set())
    selected = None if prior is None or ids is None else prior | set(ids)
    session.COORDINATOR.metrics["coalesced"] += int(key in _TARGETS)
    _TARGETS[key] = selected
    invalidate(scene, root, selected)
    token = session.COORDINATOR.enqueue(key, lambda generation: scan_root(key, generation))
    session.REPOSITORY.state(key, "PENDING", token)
    ensure_timer()


def resolve_root(key):
    if key[0] != session.EPOCH:
        return None, None
    scene = next((s for s in bpy.data.scenes if session.id_token(s) == key[1]), None)
    root = None if scene is None else next((r for r in scene.objects
           if session.id_token(r) == key[2] and r.get("anthroforge_root")), None)
    return scene, root


def scan_root(key, generation):
    scene, root = resolve_root(key)
    if root is None:
        return remove_root(key)
    depsgraph, runtime = capture.capture_root(scene, root)
    colliders = []
    yield from capture.capture_colliders(scene, root, depsgraph, colliders)
    world = session.measure("native_world", capture.preflight._collision_world, tuple(colliders), tuple(row.generation for row in colliders))
    yield
    yield from scan_fibers(key, generation, scene, root, colliders, world, runtime)
    if session.COORDINATOR.current(key, generation):
        session.REPOSITORY.state(key, "COMPLETE", generation)
        _TARGETS.pop(key, None)


def scan_fibers(key, generation, scene, root, colliders, world, runtime):
    selected, live = _TARGETS.get(key), set()
    valid = lambda: session.COORDINATOR.current(key, generation) and resolve_root(key)[1] == root
    for fiber in root.af_vcp_system.fibers:
        ref, _signature = identity(scene, root, fiber)
        live.add(ref.scope)
        if selected is None or str(fiber.id) in selected:
            yield from capture.check_fiber(scene, root, fiber, colliders, world, runtime, generation, valid)
        yield
    for scope in session.scopes_for(scene, root):
        if scope[3] == "FIBER" and scope not in live:
            session.REPOSITORY.remove(scope)


def remove_root(key):
    for scope in tuple(session.REPOSITORY.states):
        if scope[:3] == key[:3]:
            session.REPOSITORY.remove(scope)
    _TARGETS.pop(key, None)


def notify_action(root=None, scene=None, dirty=None, event_type="CHANGE", full=False):
    if not _ENABLED:
        return
    session.COORDINATOR.on_action(dict(dirty=dirty, event_type=event_type, full=full), (scene, root))


def reconcile_membership(scene):
    if not _ENABLED or scene is None:
        return
    key = session.id_token(scene)
    current = tuple(session.id_token(root) for root in scene.objects if root.get("anthroforge_root"))
    if _MEMBERSHIPS.get(key, ()) != current:
        _MEMBERSHIPS[key] = current
        session.COORDINATOR.check_all(None)


def structural_change(root, ids=None):
    session.retire(root, ids)


def ensure_timer():
    if _ENABLED and not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=0.1)


def tick():
    if not _ENABLED:
        return None
    return 0.01 if session.COORDINATOR.tick() else None


@persistent
def before_change(_dummy):
    from ..utils import clear_active_af_roots
    clear_active_af_roots()
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
    _TARGETS.clear(); _MEMBERSHIPS.clear(); session.reset("CANCELLED")


@persistent
def after_change(_dummy):
    if _ENABLED:
        session.COORDINATOR.check_all(None)


def handlers():
    return (("load_pre", before_change), ("undo_pre", before_change), ("redo_pre", before_change),
            ("load_post", after_change), ("undo_post", after_change), ("redo_post", after_change))


def register():
    global _ENABLED
    _ENABLED = True
    if "fiber_hard_anchor.v1" not in session.COORDINATOR.factories:
        session.COORDINATOR.register(InvalidAnchorProvider())
    for name, callback in handlers():
        group = getattr(bpy.app.handlers, name)
        if callback not in group:
            group.append(callback)
    after_change(None)


def unregister():
    global _ENABLED
    _ENABLED = False
    before_change(None)
    for name, callback in handlers():
        group = getattr(bpy.app.handlers, name)
        if callback in group:
            group.remove(callback)
    session.COORDINATOR.factories.clear()

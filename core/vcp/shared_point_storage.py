"""Native shared bindings with compatibility accessors for existing Fiber tools."""
from uuid import uuid4

from .prop_update_guard import suppress_vcp_prop_updates, vcp_prop_updates_suppressed

_POINT_INDEX = {}
_USER_INDEX = {}


def clear_indexes(_unused=None, _context=None):
    _POINT_INDEX.clear()
    _USER_INDEX.clear()


def _point_index(owner, system):
    root = owner.id_data
    key = (int(root.as_pointer()), len(system.authored_points))
    cached = _POINT_INDEX.get(key)
    if cached is None:
        cached = {p.id: p for p in system.authored_points}
        _POINT_INDEX.clear()
        _POINT_INDEX[key] = cached
    return cached


def slots(fiber):
    if str(fiber.topology_mode) == "LOOP":
        return tuple((item, "point_id", "LOOP") for item in fiber.loop_anchors)
    middle = tuple((item, "point_id", "MID") for item in fiber.mid_touches)
    return ((fiber, "a_point_id", "START"),) + middle + ((fiber, "b_point_id", "END"),)


def point_record(owner, slot):
    system = getattr(getattr(owner, "id_data", None), "af_vcp_system", None)
    key = str(getattr(owner, slot, ""))
    if not key or system is None:
        return None
    return _point_index(owner, system).get(key)


def endpoint_record(fiber, side):
    from types import SimpleNamespace
    point = point_record(fiber, side + "_point_id")
    if point is not None:
        return point
    return SimpleNamespace(parent_id=getattr(fiber, side + "_parent_id"),
                           attach_param=getattr(fiber, side + "_attach_param"), normal_offset=0.0)


def _legacy_value(owner, name, default):
    return owner.id_properties_ensure().get(name, default)


def read_binding(owner, slot, field, legacy, default):
    point = point_record(owner, slot)
    return getattr(point, field) if point is not None else _legacy_value(owner, legacy, default)


def ensure_point(owner, slot):
    point = point_record(owner, slot)
    if point is not None:
        return point
    prefix = slot[:2] if slot in {"a_point_id", "b_point_id"} else ""
    with suppress_vcp_prop_updates():
        point = owner.id_data.af_vcp_system.authored_points.add()
        point.id = str(uuid4())
        point.parent_id = _legacy_value(owner, prefix + "parent_id", "")
        point.attach_param = _legacy_value(owner, prefix + "attach_param", "0.0")
        point.normal_offset = _legacy_value(owner, "normal_offset", 0.0) if not prefix else 0.0
        setattr(owner, slot, point.id)
    return point


def binding_getter(slot, field, legacy, default):
    def get(owner):
        return read_binding(owner, slot, field, legacy, default)
    return get


def binding_setter(slot, field):
    def set_value(owner, value):
        setattr(ensure_point(owner, slot), field, value)
    return set_value


def point_users(root, point_id):
    fibers = tuple(root.af_vcp_system.fibers)
    signature = tuple((f.id, tuple((getattr(o, s), r) for o, s, r in slots(f))) for f in fibers)
    key = int(root.as_pointer())
    saved = _USER_INDEX.get(key)
    if saved is None or saved[0] != signature:
        users = {}
        for fiber, (_, references) in zip(fibers, signature):
            for index, (point, role) in enumerate(references):
                users.setdefault(point, []).append((fiber, index, role))
        saved = signature, {p: tuple(rows) for p, rows in users.items()}
        _USER_INDEX[key] = saved
    return saved[1].get(point_id, ())


def point_updated(point, context):
    if vcp_prop_updates_suppressed() or not point.id:
        return
    from ...app.runtime_api import schedule_context
    from ..deps.dirty_hints import dirty_hints_for
    ids = {fiber.id for fiber, _, _ in point_users(point.id_data, point.id) if fiber.id}
    if ids:
        _invalidate(point.id_data, context, ids)
        schedule_context(context, dirty_hints=dirty_hints_for("FIBER", ids), event_type="FIBER_UPDATE",
                         dirty_aspects={"FIBER": {"RELATIONSHIP", "ATTACHMENT"}})


def _invalidate(root, context, ids):
    from .fiber_anchor_preflight import invalidate_fiber_anchor_preflight, clear_transient_fiber_attachment_statuses
    invalidate_fiber_anchor_preflight(getattr(context, "scene", None), root, ids)
    clear_transient_fiber_attachment_statuses(root, ids)


def migrate_root(root):
    """Storage-only migration; preserves cached geometry and never schedules solves."""
    system = root.af_vcp_system
    previous = int(system.point_schema_version)
    with suppress_vcp_prop_updates():
        for fiber in system.fibers:
            for owner, slot, _role in slots(fiber):
                ensure_point(owner, slot)
        system.point_schema_version = 1
    if previous == 0:
        from ...adapters.authoring.shared_point_migration import upgrade_owned_documents
        upgrade_owned_documents(root)


def migrate_loaded(_unused=None):
    import bpy
    clear_indexes()
    for root in bpy.data.objects:
        if hasattr(root, "af_vcp_system") and len(root.af_vcp_system.fibers):
            migrate_root(root)


def _migrate_when_ready():
    import bpy
    if not hasattr(bpy.data, "objects"):
        return 0.05
    migrate_loaded()


def _initialize_loaded():
    """Addon enable restricts bpy.data; migrate after registration or file loading."""
    import bpy
    if hasattr(bpy.data, "objects"):
        return migrate_loaded()
    if not bpy.app.timers.is_registered(_migrate_when_ready):
        bpy.app.timers.register(_migrate_when_ready, first_interval=0.0)


def register():
    import bpy
    from bpy.app.handlers import persistent
    persistent(migrate_loaded)
    persistent(clear_indexes)
    for handlers in (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if clear_indexes not in handlers:
            handlers.insert(0, clear_indexes)
    if migrate_loaded not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.insert(0, migrate_loaded)
    _initialize_loaded()


def unregister():
    import bpy
    if bpy.app.timers.is_registered(_migrate_when_ready):
        bpy.app.timers.unregister(_migrate_when_ready)
    if migrate_loaded in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(migrate_loaded)
    for handlers in (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if clear_indexes in handlers:
            handlers.remove(clear_indexes)
    clear_indexes()

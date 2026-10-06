"""Blender lifecycle adapter; one coordinator serializes all root jobs."""
from dataclasses import asdict
import bpy
from bpy.app.handlers import persistent
from .capture import DomainCaptureAdapter, identity, clear, remove
from ..muscle_stacking.native import NativeStackEngine
from ..muscle_stacking.publication import PublicationAdapter
from .coordinator import DetectionCoordinator
from . import configuration
from ..muscle_relationships.lifecycle import RelationshipLifecycle

COORDINATOR = DetectionCoordinator(DomainCaptureAdapter(), NativeStackEngine, publisher=PublicationAdapter(), lifecycle=RelationshipLifecycle())
ENABLED = False
MEMBERS = {}
TRANSFORMS = {}


def key(scene, root):
    return identity(scene), identity(root)


def refresh(scene, root, explicit=False):
    if not ENABLED and not explicit: return
    token = key(scene, root)
    if token not in MEMBERS: initialize_transforms(scene, root)
    MEMBERS[token] = membership(root)
    enqueue(token, scene, root, explicit)
    ensure_timer()


def enqueue(token, scene, root, explicit):
    from .model import DetectionResult
    try:
        COORDINATOR.invalidate(token, (scene, root), configuration.settings(root),
            explicit or configuration.read(root)['automatic'], delay=0.0 if explicit else .150)
    except ValueError as error:
        COORDINATOR.invalidate(token, (scene, root), None, False)
        PublicationAdapter().prepare((scene, root))
        COORDINATOR.entries[token].result = DetectionResult(COORDINATOR.serial, 'failed', issues=({'message': str(error)},))


def notify(root, scene, dirty=None, event_type='', full=False):
    if event_type.upper() in ('SELECTION', 'DISPLAY', 'VISIBILITY'): return
    if full or not dirty or any(dirty.get(k) for k in ('MUSCLE', 'FIBER', 'FIBER_SURFACE', 'SCP', 'ROOT')):
        refresh(scene, root)


def inspect(scene, root):
    from ..muscle_relationships.inspection import enrich
    result = COORDINATOR.inspect(key(scene, root)); value = asdict(result)
    value.update(inspect_configuration(root), result_revision=f'{COORDINATOR.epoch}:{result.generation}',
        completeness='complete' if result.status == 'complete' else 'incomplete')
    return enrich(root, value)


def inspect_configuration(root):
    try: return configuration.inspect(root)
    except ValueError as error:
        return dict(settings=dict(configuration.DEFAULT), groups={}, configuration_revision=None, configuration_error=str(error))


def footprint(scene, root, index, revision, order=False):
    try: token = tuple(int(v) for v in revision.split(':'))
    except (ValueError, AttributeError): raise ValueError('PAIR_STALE_RESULT')
    entry = COORDINATOR.entries.get(key(scene, root))
    if entry is None or token != (COORDINATOR.epoch, entry.generation) or entry.result.status not in ('complete', 'incomplete'): raise ValueError('PAIR_STALE_RESULT')
    backend = entry.backend
    result = backend.order_footprint(index, token[1]) if order else backend.footprint(index, token[1])
    return dict(result, domains={str(k): dict(key=asdict(v.key), group=v.group, revision=v.revision,
        displacement_allowance=v.displacement, parts=v.parts.tolist(),
        source_faces=v.sources.tolist(), triangles=v.faces.tolist()) for k, v in backend.domains.items()
        if v.key in (backend.domains[backend.rows[index].first].key, backend.domains[backend.rows[index].second].key)})


def ensure_timer():
    if ENABLED and not bpy.app.timers.is_registered(tick): bpy.app.timers.register(tick, first_interval=.05)


def tick():
    if not ENABLED: return None
    active = COORDINATOR.tick()
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D': area.tag_redraw()
    return .05 if active else None


def roots(scene):
    return tuple(o for o in scene.objects if o.get('anthroforge_root'))


def membership(root):
    return tuple((m.id, str(m.get('af_pair_group_id', ''))) for m in root.af_vcp_system.muscles)


def reconcile(scene):
    from ..muscle_relationships.blender_identity import discover
    live = set()
    for root in roots(scene):
        discover(root)
        token = key(scene, root); live.add(token); current = membership(root)
        if token not in MEMBERS: initialize_transforms(scene, root)
        if MEMBERS.get(token) != current: MEMBERS[token] = current; refresh(scene, root)
    for token in tuple(MEMBERS):
        if token[0] == identity(scene) and token not in live:
            MEMBERS.pop(token); COORDINATOR.remove(token); remove(token[1])


def initialize_transforms(scene, root):
    for obj in scene.objects:
        if watches_transform(obj) and (obj == root or obj.get('af_root_name') == root.name):
            TRANSFORMS[identity(obj)] = tuple(float(v) for row in obj.matrix_world for v in row)


def watches_transform(obj):
    return obj.get('anthroforge_root') or obj.get('af_muscle_surface') in ('BASE', 'INFL')


@persistent
def changed(scene, depsgraph):
    if not ENABLED: return
    reconcile(scene); affected = set()
    for update in depsgraph.updates:
        obj = update.id
        if not isinstance(obj, bpy.types.Object): continue
        if not watches_transform(obj): continue
        token = identity(obj); transform = tuple(float(v) for row in obj.matrix_world for v in row)
        if token in TRANSFORMS and TRANSFORMS[token] != transform: affected.add(obj.get('af_root_name', obj.name))
        TRANSFORMS[token] = transform
    for root in roots(scene):
        if root.name in affected: refresh(scene, root)


@persistent
def before_change(_dummy):
    from ..muscle_relationships.blender_identity import suspend
    suspend()
    if bpy.app.timers.is_registered(tick): bpy.app.timers.unregister(tick)
    COORDINATOR.reset(); clear(); MEMBERS.clear(); TRANSFORMS.clear()


@persistent
def after_change(_dummy):
    from ..muscle_relationships.blender_identity import reset
    reset()
    if ENABLED:
        for scene in bpy.data.scenes: reconcile(scene)


def handlers():
    return (('load_pre', before_change), ('undo_pre', before_change), ('redo_pre', before_change),
        ('load_post', after_change), ('undo_post', after_change), ('redo_post', after_change), ('depsgraph_update_post', changed))


def register():
    global ENABLED
    ENABLED = True
    for name, callback in handlers():
        group = getattr(bpy.app.handlers, name)
        if callback not in group: group.append(callback)
    after_change(None)


def unregister():
    global ENABLED
    ENABLED = False; before_change(None)
    for name, callback in handlers():
        group = getattr(bpy.app.handlers, name)
        if callback in group: group.remove(callback)

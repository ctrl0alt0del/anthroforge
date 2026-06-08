from .context import addon_context, context_from_blender
from .runtime_intents import dispatch_runtime_intent as dispatch_app_runtime_intent
from .runtime_requests import runtime_request
from .runtime_sync import emit_sync


def sync_context(context=None, dirty_hints=None, bake=False, source="manual", event_type="UPDATE", payload=None):
    ctx = context_from_blender(context)
    req = runtime_request(dirty_hints=dirty_hints, bake=bake, source=source, event_type=event_type, payload=payload)
    emit_sync(_sync_fn(), ctx, req)


def sync_scene(root=None, scene=None, dirty_hints=None, bake=False, source="manual", event_type="UPDATE", payload=None):
    ctx = addon_context(root=root, scene=scene)
    req = runtime_request(dirty_hints=dirty_hints, bake=bake, source=source, event_type=event_type, payload=payload)
    emit_sync(_sync_fn(), ctx, req)


def dispatch_intent_context(context=None, *, intent_type="", entity_type="", entity_id="", payload=None, dirty_hints=None, source="manual", event_type="UPDATE"):
    ctx = context_from_blender(context)
    dispatch_app_runtime_intent(ctx, _enqueue_fn(), _sync_fn(), _dirty_hints_for(), _empty_dirty_hints(), intent_type=intent_type, entity_type=entity_type, entity_id=entity_id, payload=payload, dirty_hints=dirty_hints, source=source, event_type=event_type)


def _sync_fn():
    try:
        from ..core.visualization.sync_runner import sync_from_dirty_hints
    except ImportError:
        from core.visualization.sync_runner import sync_from_dirty_hints
    return sync_from_dirty_hints


def _enqueue_fn():
    try:
        from ..core.deps.runtime_intents import enqueue_runtime_intent
    except ImportError:
        from core.deps.runtime_intents import enqueue_runtime_intent
    return enqueue_runtime_intent


def _dirty_hints_for():
    try:
        from ..core.deps.dirty_hints import dirty_hints_for
    except ImportError:
        from core.deps.dirty_hints import dirty_hints_for
    return dirty_hints_for


def _empty_dirty_hints():
    try:
        from ..core.deps.dirty_hints import empty_dirty_hints
    except ImportError:
        from core.deps.dirty_hints import empty_dirty_hints
    return empty_dirty_hints

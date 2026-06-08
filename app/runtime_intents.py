from .runtime_requests import runtime_request, seeded_dirty_hints
from .runtime_sync import emit_sync


def dispatch_runtime_intent(ctx, enqueue_fn, sync_fn, dirty_hints_for, empty_dirty_hints, *, intent_type="", entity_type="", entity_id="", payload=None, dirty_hints=None, source="manual", event_type="UPDATE"):
    if ctx.root is None:
        return
    if not enqueue_fn(ctx.root, intent_type, entity_type, entity_id, payload, source, event_type):
        return
    request = _intent_request(dirty_hints, entity_type, entity_id, dirty_hints_for, empty_dirty_hints, source, event_type)
    emit_sync(sync_fn, ctx, request)


def _intent_request(dirty_hints, entity_type, entity_id, dirty_hints_for, empty_dirty_hints, source, event_type):
    hints = seeded_dirty_hints(dirty_hints, entity_type, entity_id, dirty_hints_for, empty_dirty_hints)
    return runtime_request(dirty_hints=hints, source=source, event_type=event_type)

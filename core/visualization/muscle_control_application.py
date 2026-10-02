"""Apply one reserved observation with a synchronous, scoped evaluated graph."""
from ..deps import muscle_control_intents as inputs


def apply_input(sync, root, scene, obj, value=None, depsgraph=None, collection=None, runtime=False):
    value = value or inputs.reserve_input(root, scene, obj)
    if value is None or value.owners != inputs.owners(root, scene, obj):
        return None
    if _unsafe_direct(sync, value, runtime):
        inputs.dispatch_input(root, scene, value, deferred=True)
        return None
    if not inputs.claim_input(value):
        return None
    return _consume(sync, root, scene, obj, value, depsgraph, collection)


def _unsafe_direct(sync, value, runtime):
    from .sync_runner import runtime_request_active, control_input_pending
    return inputs.input_busy() or (not runtime and
        (sync._syncing or runtime_request_active() or control_input_pending(value)))


def _consume(sync, root, scene, obj, value, depsgraph, collection):
    success = False
    try:
        with inputs.acquisition_guard():
            changed = _with_graph(sync, root, scene, obj, value, depsgraph, collection)
            success = True
            return changed
    except inputs.ControlContextChanged:
        success = None
        inputs.dispatch_input(root, scene, value, fresh_context=True)
        return None
    finally:
        inputs.finish_input(value, success)


def _with_graph(sync, root, scene, obj, value, depsgraph, collection):
    revision = inputs.context_revision()
    graph = depsgraph or inputs.acquire_graph(root, scene)
    inputs.require_context(revision)
    return _apply(sync, root, scene, obj, value, graph, collection)


def _apply(sync, root, scene, obj, value, graph, collection):
    import bpy
    record = inputs.input_record(value)
    collection = collection or bpy.data.collections.get(sync.collection_name)
    if record is None or record.root != root or record.scene != scene or record.control != obj:
        return None
    if collection is None or graph is None:
        raise RuntimeError('Muscle control has no evaluated context')
    changed = set()
    sync._process_inflation_ctrl_update(root, collection, obj, changed, value, graph)
    return next(iter(changed), None)


def apply_request_inputs(ctx, intents, apply_intent):
    values = dict((ctx.gate_meta or {}).get('payload', {}) or {})
    value = values.get('muscle_control_input')
    pending = ([value] if value is not None else []) + list(inputs.retry_inputs(ctx))
    controls = [intent.payload.get('muscle_control_input') for intent in intents
                if intent.intent_type == 'CONTROL/MUSCLE_INFLATION']
    changed = _apply_inputs(ctx, pending + [item for item in controls if item is not None])
    for intent in intents:
        if intent.intent_type != 'CONTROL/MUSCLE_INFLATION':
            for kind, ids in (apply_intent(ctx.root, ctx.scene, intent) or {}).items():
                changed.setdefault(kind, set()).update(ids)
    return changed


def _apply_inputs(ctx, pending):
    from .muscle_sync import register_muscle_sync
    changed, seen = {}, set()
    for value in dict((inputs.input_key(item), item) for item in pending).values():
        record = inputs.input_record(value)
        if record is None:
            continue
        if value.muscle_id in seen:
            inputs.dispatch_input(ctx.root, ctx.scene, value)
            continue
        seen.add(value.muscle_id)
        mid = apply_input(register_muscle_sync(), ctx.root, ctx.scene, record.control, value, runtime=True)
        if mid:
            changed.setdefault('MUSCLE', set()).add(mid)
    return changed

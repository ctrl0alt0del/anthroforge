from .results import failure, success

try:
    from ..runtime_api import dispatch_intent_context
    from ..queries.attachment_anchor_lock import child_anchor_lock_panel_state
    from ..queries.scp import active_scp_from_context
    from ...core.scp_runtime.child_anchor_lock import clear_locked_child_anchor_index, set_locked_child_anchor_index
except ImportError:
    from app.runtime_api import dispatch_intent_context
    from app.queries.attachment_anchor_lock import child_anchor_lock_panel_state
    from app.queries.scp import active_scp_from_context
    from core.scp_runtime.child_anchor_lock import clear_locked_child_anchor_index, set_locked_child_anchor_index


def set_active_scp_child_anchor_lock(context):
    scp, state = _active_state(context)
    if scp is None or not state.can_set:
        return failure(_state_message(state, "Select one child anchor element to lock."))
    set_locked_child_anchor_index(scp, state.mode, state.selected_index)
    _dispatch_recapture(context, scp.id)
    return success(f"Locked child anchor to {_label(state.mode)} {state.selected_index}.")


def clear_active_scp_child_anchor_lock(context):
    scp, state = _active_state(context)
    if scp is None or not state.has_lock:
        return failure(_state_message(state, "No locked child anchor to clear."))
    clear_locked_child_anchor_index(scp, state.mode)
    _dispatch_recapture(context, scp.id)
    return success(f"Cleared locked {_label(state.mode)} anchor.")


def _active_state(context):
    scp = active_scp_from_context(context)
    return scp, child_anchor_lock_panel_state(context, scp)


def _dispatch_recapture(context, scp_id):
    dispatch_intent_context(context, intent_type="SCP/RECAPTURE_ATTACHMENT", entity_type="SCP", entity_id=str(scp_id or ""), source="operator", event_type="UPDATE")


def _state_message(state, fallback):
    return fallback if state is None or not state.message else state.message


def _label(mode):
    return "face" if str(mode or "").upper() == "FACE_CENTER" else "vertex"

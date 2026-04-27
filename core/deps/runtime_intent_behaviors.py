from .control_behaviors import apply_control_intent
from .controls import ControlIntent
from ..scp_runtime.attachment_runtime import recapture_attachment_for_scp


def _control_type(intent_type):
    _, _, suffix = str(intent_type or "").partition("/")
    return suffix


def _apply_control_runtime_intent(root, scene, intent):
    control_intent = ControlIntent(_control_type(intent.intent_type), intent.payload)
    return apply_control_intent(root, scene, control_intent)


def _apply_scp_recapture(root, scene, intent):
    sid = str(intent.entity_id or intent.payload.get("scp_id") or "")
    if not sid or not recapture_attachment_for_scp(root, scene, sid):
        return {}
    return {"SCP": {sid}}


def apply_runtime_intent(root, scene, intent):
    intent_type = str(getattr(intent, "intent_type", "") or "")
    if intent_type.startswith("CONTROL/"):
        return _apply_control_runtime_intent(root, scene, intent)
    if intent_type == "SCP/RECAPTURE_ATTACHMENT":
        return _apply_scp_recapture(root, scene, intent)
    return {}

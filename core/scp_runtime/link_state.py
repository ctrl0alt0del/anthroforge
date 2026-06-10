from .common import set_prop_raw
from .runtime_state import restore_attachment_runtime, snapshot_attachment_runtime


def snapshot_link_state(scp):
    return {"parent_id": getattr(scp, "parent_id", ""), "attachment_runtime": snapshot_attachment_runtime(scp)}


def restore_link_state(scp, snapshot):
    state = dict(snapshot or {})
    set_prop_raw(scp, "parent_id", state.get("parent_id", ""))
    restore_attachment_runtime(scp, state.get("attachment_runtime", {}))

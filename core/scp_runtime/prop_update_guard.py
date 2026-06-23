import builtins
from contextlib import contextmanager

from .common import as_id, set_prop_raw

_STATE_KEY = "_af_scp_prop_update_guard_state"


def _state():
    state = getattr(builtins, _STATE_KEY, None)
    if state is None:
        state = {"depth": 0}
        setattr(builtins, _STATE_KEY, state)
    return state


def scp_prop_updates_suppressed():
    return _state()["depth"] > 0


@contextmanager
def suppress_scp_prop_updates():
    state = _state()
    state["depth"] += 1
    try:
        yield
    finally:
        state["depth"] -= 1


def set_parent_id_raw(scp, parent_id):
    with suppress_scp_prop_updates():
        set_prop_raw(scp, "parent_id", as_id(parent_id))

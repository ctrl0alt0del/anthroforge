import builtins
from contextlib import contextmanager

_STATE_KEY = "_af_vcp_prop_update_guard_state"


def _state():
    state = getattr(builtins, _STATE_KEY, None)
    if state is None:
        state = {"depth": 0}
        setattr(builtins, _STATE_KEY, state)
    return state


def vcp_prop_updates_suppressed():
    return _state()["depth"] > 0


@contextmanager
def suppress_vcp_prop_updates():
    state = _state()
    state["depth"] += 1
    try:
        yield
    finally:
        state["depth"] -= 1

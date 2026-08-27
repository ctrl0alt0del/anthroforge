"""Request-local Fiber engine selection."""

from dataclasses import dataclass
from enum import Enum
import os


FIBER_ENGINE_ENV = "AF_FIBER_ENGINE"


class FiberEngineKind(str, Enum):
    V1 = "V1"
    V2 = "V2"
    V3 = "V3"


@dataclass(frozen=True)
class FiberEngineSelection:
    requested: object
    actual: object
    source: str
    fallback_reason: str = ""
    error: str = ""

    @property
    def valid(self):
        return not self.error and self.actual is not None


def resolve_fiber_engine(explicit=None, environ=None):
    source, raw = _selection_value(explicit, environ)
    try:
        engine = FiberEngineKind(raw)
    except ValueError:
        return FiberEngineSelection(None, None, source, error=_invalid_message(raw))
    return FiberEngineSelection(engine, engine, source)


def select_fiber_engine(topology, explicit=None, environ=None):
    selection = resolve_fiber_engine(explicit, environ)
    if not selection.valid or selection.requested is FiberEngineKind.V1:
        return selection
    if str(topology or "OPEN").upper() == "OPEN":
        return selection
    reason = f"{selection.requested.value}_TOPOLOGY_COMPATIBILITY"
    return FiberEngineSelection(selection.requested, FiberEngineKind.V1,
                                selection.source, reason)


def _selection_value(explicit, environ):
    if explicit is not None:
        return "EXPLICIT", _normalized(explicit)
    values = os.environ if environ is None else environ
    if FIBER_ENGINE_ENV in values:
        return "ENVIRONMENT", _normalized(values.get(FIBER_ENGINE_ENV))
    return "DEFAULT", FiberEngineKind.V2.value


def _normalized(value):
    return str(getattr(value, "value", value) or "")


def _invalid_message(value):
    return f"Invalid {FIBER_ENGINE_ENV} value: {value!r}; expected V1, V2, or V3."

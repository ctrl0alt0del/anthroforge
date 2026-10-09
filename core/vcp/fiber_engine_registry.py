"""Stable registry for request-local Fiber engines."""

from dataclasses import dataclass, replace

from .fiber_engine_selection import FiberEngineKind, select_fiber_engine
from .v2.production import V2_PRODUCTION_VERSION, v2_backend_status
from .v3.production import V3_PRODUCTION_VERSION, v3_backend_status


V1_PRODUCTION_VERSION = "fiber-v1-legacy-1"


@dataclass(frozen=True)
class FiberEngineAdapter:
    kind: FiberEngineKind
    version: str
    requires_native_backend: bool = False


FIBER_ENGINE_REGISTRY = {
    FiberEngineKind.V1: FiberEngineAdapter(FiberEngineKind.V1, V1_PRODUCTION_VERSION),
    FiberEngineKind.V2: FiberEngineAdapter(FiberEngineKind.V2, V2_PRODUCTION_VERSION, True),
    FiberEngineKind.V3: FiberEngineAdapter(FiberEngineKind.V3, V3_PRODUCTION_VERSION, True),
}


def selection_for_fiber(fiber, explicit=None, environ=None):
    from .attachment_surface import muscle_backed
    topology = getattr(fiber, "topology_mode", "OPEN")
    selection = select_fiber_engine(topology, explicit, environ)
    if muscle_backed(fiber) and selection.actual is not FiberEngineKind.V3:
        return replace(selection, error='Muscle parents require the native V3 engine.', actual=None)
    return selection


def adapter_for_selection(selection):
    return None if not selection.valid else FIBER_ENGINE_REGISTRY[selection.actual]


def selected_backend_status(selection):
    adapter = adapter_for_selection(selection)
    if not adapter or not adapter.requires_native_backend: return None
    return v3_backend_status() if adapter.kind is FiberEngineKind.V3 else v2_backend_status()

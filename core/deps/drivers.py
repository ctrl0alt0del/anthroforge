from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, Optional, Set


@dataclass
class DependencyRuntimeContext:
    root: object
    scene: object
    dirty: Dict[str, Set[str]]
    is_full: bool
    entity_sets: Dict[str, Set[str]]
    adjacency: dict
    scc_idx: dict
    scc_sizes: dict
    gate_meta: dict = field(default_factory=dict)
    bake: bool = False


class DependencyDriver:
    name = "base_driver"

    def entity_types(self):
        return tuple()

    def build_graph(self, root, graph, entity_sets):
        return

    def apply_constraints(self, ctx: DependencyRuntimeContext):
        return {}

    def sync(self, root, scene, is_full, impacted, bake, gate_meta=None):
        return

    def post_sync(self, root, scene, is_full, impacted, bake):
        return


_DRIVERS = OrderedDict()
_DRIVER_GENERATION = 0


def register_dependency_driver(driver: DependencyDriver, replace: bool = False):
    global _DRIVER_GENERATION
    name = str(getattr(driver, "name", "") or "").strip()
    if not name:
        raise ValueError("driver.name is required")
    if name in _DRIVERS and not replace:
        raise ValueError(f"dependency driver already registered: {name}")
    _DRIVERS[name] = driver
    _DRIVER_GENERATION += 1


def dependency_driver_generation():
    return _DRIVER_GENERATION


def get_dependency_drivers():
    return tuple(_DRIVERS.values())


def get_registered_entity_types():
    out = []
    seen = set()
    for d in _DRIVERS.values():
        for et in tuple(d.entity_types() or tuple()):
            u = str(et or "").strip().upper()
            if not u or u in seen:
                continue
            seen.add(u)
            out.append(u)
    return tuple(out)

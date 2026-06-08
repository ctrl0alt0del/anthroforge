from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeBuild:
    graph: object
    entity_sets: dict
    adjacency: dict
    scc_idx: dict
    scc_sizes: dict
    dirty: dict
    is_full: bool

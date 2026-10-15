"""Shared interpretation of guides captured with an existing topology."""
import numpy as np
from ..topology.model import TopologyGuide


def guide_sets(stats, guides):
    old = stored_guides(stats)
    mapping = stats.get("guide_map", ())
    by_name = {item.object_name: item for item in guides}
    current = tuple(mapped_guide(index, item, by_name) for index, item in enumerate(mapping))
    return old, tuple(item for item in current if item is not None) or tuple(guides)


def stored_guides(stats):
    return tuple(TopologyGuide(int(item["guide_index"]), item["fiber_id"], item["fiber_id"],
                               "ORIGINAL", np.asarray(item["points"]))
                 for item in stats.get("guide_layout", ()))


def mapped_guide(index, mapping, by_name):
    candidates = [by_name[name] for name in mapping.get("sources", ()) if name in by_name]
    if not candidates:
        return None
    source = max(candidates, key=lambda item: perimeter(item.points))
    return TopologyGuide(index, source.fiber_id, source.object_name, source.mirror_role, source.points)


def perimeter(points):
    values = np.asarray(points)
    return float(np.linalg.norm(np.roll(values, -1, axis=0) - values, axis=1).sum())

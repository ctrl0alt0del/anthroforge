import hashlib
import json
from dataclasses import dataclass
from enum import Enum

import numpy as np


class WarmChangeClass(str, Enum):
    GEOMETRY_ONLY = "GEOMETRY_ONLY"
    SKIN_REBUILD = "SKIN_REBUILD"
    TOPOLOGY_REBUILD = "TOPOLOGY_REBUILD"
    FULL_REBUILD = "FULL_REBUILD"


@dataclass(frozen=True)
class WarmChangeState:
    source_identity: str = ""
    source_connectivity: str = ""
    source_contact: str = ""
    collagen_settings: tuple[float, ...] = ()
    guide_layout: str = ""
    guide_pairing: str = ""
    symmetry_settings: str = ""
    density_settings: str = ""
    skin_valid: bool = True
    topology_valid: bool = True
    quad_distortion: float = 1.0
    has_skin: bool = True
    has_topology: bool = True
    geometry_state: str = ""


@dataclass(frozen=True)
class WarmChangeDecision:
    change_class: WarmChangeClass
    reasons: tuple[str, ...]
    skin_rebuild: bool
    topology_rebuild: bool


def classify_change(previous, current, force="AUTO"):
    skin_reasons = _skin_reasons(previous, current)
    topology_reasons = _topology_reasons(previous, current)
    _apply_force(skin_reasons, topology_reasons, force)
    decision = _decision(skin_reasons, topology_reasons)
    if decision.change_class == WarmChangeClass.GEOMETRY_ONLY and previous.geometry_state != current.geometry_state:
        return WarmChangeDecision(decision.change_class, ("source geometry changed",), False, False)
    return decision


def source_contact_signature(sources, margin_ratio=0.002):
    if not sources:
        return _hash(())
    bounds = [(_bounds(item.vertices)) for item in sources]
    diagonal = max(float(np.linalg.norm(np.ptp(np.vstack(bounds), axis=0))), 1e-9)
    pairs = [(sources[i].entity_id, sources[j].entity_id) for i in range(len(sources))
             for j in range(i + 1, len(sources)) if _near(bounds[i], bounds[j], margin_ratio * diagonal)]
    return _hash(sorted(pairs))


def guide_pairing_signature(guides):
    descriptors = [_guide_descriptor(item) for item in guides]
    pending, pairs = list(range(len(guides))), []
    while pending:
        first = pending.pop(0)
        compatible = [index for index in pending if _nested(descriptors[first], descriptors[index])]
        if compatible:
            second = min(compatible, key=lambda index: _pair_score(descriptors[first], descriptors[index]))
            pending.remove(second); pairs.append(sorted((guides[first].fiber_id, guides[second].fiber_id)))
    return _hash(sorted(pairs))


def settings_signature(payload):
    return _hash(payload)


def _skin_reasons(previous, current):
    reasons = []
    if not previous.has_skin:
        reasons.append("draft skin is missing")
    _changed(reasons, previous.source_identity, current.source_identity, "contributors changed")
    _changed(reasons, previous.source_connectivity, current.source_connectivity, "source connectivity changed")
    _changed(reasons, previous.source_contact, current.source_contact, "possible contact or separation")
    if _large_collagen_change(previous.collagen_settings, current.collagen_settings):
        reasons.append("collagen envelope changed substantially")
    if not previous.skin_valid or not current.skin_valid:
        reasons.append("warm skin validation failed")
    return reasons


def _topology_reasons(previous, current):
    reasons = []
    if not previous.has_topology:
        reasons.append("topology is missing")
    _changed(reasons, previous.guide_layout, current.guide_layout, "guide layout changed")
    _changed(reasons, previous.guide_pairing, current.guide_pairing, "nested guide pairing changed")
    _changed(reasons, previous.symmetry_settings, current.symmetry_settings, "symmetry settings changed")
    _changed(reasons, previous.density_settings, current.density_settings, "topology density changed")
    if not previous.topology_valid or not current.topology_valid or current.quad_distortion > 8.0:
        reasons.append("quad distortion is irreparable")
    return reasons


def _apply_force(skin_reasons, topology_reasons, force):
    if force in {"SKIN", "FULL"}:
        skin_reasons.append("skin rebuild requested")
    if force in {"TOPOLOGY", "FULL"}:
        topology_reasons.append("topology rebuild requested")


def _decision(skin_reasons, topology_reasons):
    skin, topology = bool(skin_reasons), bool(topology_reasons)
    reasons = tuple((*skin_reasons, *topology_reasons))
    return _decision_from_flags(skin, topology, *reasons)


def _decision_from_flags(skin, topology, *reasons):
    classes = {(False, False): WarmChangeClass.GEOMETRY_ONLY,
               (True, False): WarmChangeClass.SKIN_REBUILD,
               (False, True): WarmChangeClass.TOPOLOGY_REBUILD,
               (True, True): WarmChangeClass.FULL_REBUILD}
    return WarmChangeDecision(classes[(skin, topology)], tuple(reasons), skin, topology)


def _large_collagen_change(old, new):
    if len(old) != len(new):
        return True
    if not old and not new:
        return False
    delta = np.abs(np.asarray(old, float) - np.asarray(new, float))
    scale = np.maximum(np.abs(np.asarray(old, float)), 0.002)
    return bool(np.any((delta > 0.002) & (delta / scale > 0.2)))


def _changed(reasons, old, new, message):
    if old and new and old != new:
        reasons.append(message)


def _bounds(vertices):
    values = np.asarray(vertices, dtype=float)
    return values.min(axis=0), values.max(axis=0)


def _near(first, second, margin):
    return bool(np.all(first[0] <= second[1] + margin)
                and np.all(second[0] <= first[1] + margin))


def _guide_descriptor(guide):
    points = np.asarray(guide.points, dtype=float)
    center, extent = points.mean(axis=0), np.linalg.norm(np.ptp(points, axis=0))
    perimeter = np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1).sum()
    return center, max(float(extent), 1e-9), max(float(perimeter), 1e-9)


def _nested(first, second):
    distance = np.linalg.norm(first[0] - second[0]) / max(first[1], second[1])
    ratio = min(first[2], second[2]) / max(first[2], second[2])
    return bool(distance < 0.35 and 0.2 <= ratio <= 0.95)


def _pair_score(first, second):
    return float(np.linalg.norm(first[0] - second[0]) / max(first[1], second[1]))


def _hash(payload):
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode()).hexdigest()

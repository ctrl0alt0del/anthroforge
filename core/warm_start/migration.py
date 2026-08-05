from dataclasses import asdict

import numpy as np

from ..draft_skin.bindings import binding_quality, build_skin_bindings
from ..draft_skin.model import SkinResult
from ..draft_skin.validation import validate_mesh
from ..topology.bindings import build_topology_guide_binding, build_topology_skin_binding
from ..topology.model import TopologyResult
from ..topology.validation import validate_topology
from .invalidation import guide_pairing_signature, settings_signature, source_contact_signature
from .signatures import geometry_state_hash, guide_layout_signature
from .signatures import solver_settings_hash, source_connectivity_signature
from .signatures import source_identity_signature, structural_signature


def prepare_legacy_skin(vertices, triangles, collagen, capture, statistics=None):
    validation = validate_mesh(vertices, triangles, True)
    _require(validation.valid, "Existing draft skin is not valid.")
    binding, quality = build_skin_bindings(vertices, capture.sources)
    _require_binding_quality(quality)
    stats = _skin_statistics(capture, vertices, triangles, statistics, quality)
    return SkinResult(vertices, triangles, collagen, stats, validation, binding)


def prepare_legacy_topology(vertices, quads, regions, face_guides, capture,
                            owners=None, lengths=None, statistics=None):
    validation = validate_topology(vertices, quads)
    _require(validation.valid, "Existing topology is not valid.")
    skin = build_topology_skin_binding(vertices, capture.vertices, capture.triangles)
    guide = build_topology_guide_binding(vertices, quads, regions, face_guides, capture.guides)
    stats = _topology_statistics(capture, vertices, quads, statistics)
    return TopologyResult(vertices, quads, regions, face_guides, stats, validation,
                          owners, lengths, skin, guide)


def _require_binding_quality(quality):
    _require(quality["unbound_percent"] <= 1.0, "Draft-skin binding coverage is insufficient.")
    _require(quality["visibility_rejected_percent"] <= 20.0,
             "Draft-skin binding visibility is insufficient.")


def _skin_statistics(capture, vertices, triangles, previous, quality):
    stats = dict(previous or {})
    stats.update(quality)
    stats.update(source_identity_signature=source_identity_signature(capture.sources),
                 source_connectivity_signature=source_connectivity_signature(capture.sources),
                 source_contact_signature=source_contact_signature(capture.sources),
                 geometry_state_hash=geometry_state_hash(capture.sources))
    stats.update(structural_signature=structural_signature(len(vertices), triangles),
                 solver_settings_hash=solver_settings_hash(capture.settings),
                 settings=asdict(capture.settings), last_update_type="prepared")
    stats.setdefault("source_map", _source_map(capture.sources))
    return stats


def _source_map(sources):
    return [{"source_index": int(item.source_index), "entity_type": item.entity_type,
             "entity_id": item.entity_id, "mirror_role": item.mirror_role,
             "object_name": item.object_name} for item in sources]


def _topology_statistics(capture, vertices, quads, previous):
    stats = dict(previous or {})
    stats.update(structural_signature=structural_signature(len(vertices), quads),
                 source_guide_layout_signature=guide_layout_signature(capture.guides),
                 guide_pairing_signature=guide_pairing_signature(capture.guides))
    stats.update(symmetry_settings_signature=_symmetry_signature(capture),
                 density_settings_signature=_density_signature(capture),
                 last_update_type="prepared")
    return stats


def _symmetry_signature(capture):
    value = capture.settings
    return settings_signature((value.symmetry_mode, value.custom_origin, value.custom_normal))


def _density_signature(capture):
    value = capture.settings
    rules = [asdict(item) for item in capture.density_rules]
    return settings_signature((value.target_quad_count, value.refinement_strategy, rules))


def _require(condition, message):
    if not condition:
        raise ValueError(message)

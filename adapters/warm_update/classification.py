import json
from dataclasses import asdict

import numpy as np

try:
    from ...core.warm_start.invalidation import (
        WarmChangeState, guide_pairing_signature, settings_signature,
        source_contact_signature,
    )
    from ...core.draft_skin.gap_settings import gap_signature
    from ...core.warm_start.signatures import (
        geometry_state_hash, guide_layout_signature, source_connectivity_signature, source_identity_signature,
    )
except ImportError:
    from core.draft_skin.gap_settings import gap_signature
    from core.warm_start.invalidation import WarmChangeState, guide_pairing_signature, settings_signature, source_contact_signature
    from core.warm_start.signatures import geometry_state_hash, guide_layout_signature, source_connectivity_signature, source_identity_signature


def previous_change_state(root, scene):
    skin, topology = _outputs(root, scene)
    skin_stats, topology_stats = _stats(skin), _stats(topology)
    return WarmChangeState(
        source_identity=skin_stats.get("source_identity_signature", ""),
        source_connectivity=skin_stats.get("source_connectivity_signature", ""),
        source_contact=skin_stats.get("source_contact_signature", ""),
        collagen_settings=_collagen_settings(skin_stats),
        guide_layout=topology_stats.get("source_guide_layout_signature", ""),
        guide_pairing=topology_stats.get("guide_pairing_signature", ""),
        symmetry_settings=topology_stats.get("symmetry_settings_signature", ""),
        density_settings=topology_stats.get("density_settings_signature", ""),
        skin_valid=skin is not None, topology_valid=_valid_topology(topology),
        quad_distortion=_quad_distortion(topology), has_skin=skin is not None,
        has_topology=topology is not None, geometry_state=skin_stats.get("geometry_state_hash", ""),
        gap_settings=skin_stats.get("gap_settings_signature", ""))


def current_change_state(skin_capture, topology_capture):
    settings = skin_capture.settings
    return WarmChangeState(
        source_identity=source_identity_signature(skin_capture.sources),
        source_connectivity=source_connectivity_signature(skin_capture.sources),
        source_contact=source_contact_signature(skin_capture.sources),
        collagen_settings=_collagen_settings({"settings": asdict(settings)}),
        guide_layout=guide_layout_signature(topology_capture.guides),
        guide_pairing=guide_pairing_signature(topology_capture.guides),
        symmetry_settings=_symmetry_signature(topology_capture),
        density_settings=_density_signature(topology_capture),
        geometry_state=geometry_state_hash(skin_capture.sources), gap_settings=gap_signature(skin_capture))


def _outputs(root, scene):
    skin = next((obj for obj in scene.objects if obj.get("af_draft_skin")
                 and obj.get("af_root_name") == root.name), None)
    topology = next((obj for obj in scene.objects if obj.get("af_topology")
                     and obj.get("af_root_name") == root.name), None)
    return skin, topology


def _stats(obj):
    if obj is None:
        return {}
    key = "af_skin_stats_json" if obj.get("af_draft_skin") else "af_topology_stats_json"
    try:
        return json.loads(obj.get(key, "{}"))
    except (TypeError, ValueError):
        return {}


def _collagen_settings(stats):
    values = stats.get("settings", {})
    names = ("minimum_offset_ratio", "collagen_depth_ratio",
             "collagen_core_ratio", "collagen_falloff_ratio")
    return tuple(float(values.get(name, 0.0)) for name in names)


def _symmetry_signature(capture):
    settings = capture.settings
    return settings_signature((settings.symmetry_mode, settings.custom_origin,
                               settings.custom_normal))


def _density_signature(capture):
    payload = {"target": capture.settings.target_quad_count,
               "refinement": capture.settings.refinement_strategy,
               "rules": [asdict(item) for item in capture.density_rules]}
    return settings_signature(payload)


def _quad_distortion(obj):
    if obj is None or not len(obj.data.polygons):
        return 1.0
    points = np.asarray([vertex.co[:] for vertex in obj.data.vertices])
    ratios = [_face_ratio(points[np.asarray(face.vertices)]) for face in obj.data.polygons]
    return float(np.quantile(ratios, 0.99))


def _face_ratio(points):
    lengths = np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1)
    return float(lengths.max() / max(lengths.min(), 1e-12))


def _valid_topology(obj):
    if obj is None:
        return False
    from ..mesh_issues import require_mesh
    try:
        vertices = np.asarray([vertex.co[:] for vertex in obj.data.vertices])
        faces = np.asarray([tuple(face.vertices) for face in obj.data.polygons], np.int32)
        require_mesh(vertices, faces, 4)
        return True
    except ValueError:
        return False

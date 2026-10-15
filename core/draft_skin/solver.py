import time

import numpy as np

from ..mesh_issues import annotate
from .constants import SOLVER_VERSION
from .gap_solver import reconstruct
from .gap_settings import gap_signature, effective_gap
from .fields import collagen_field, exterior_field, smooth_max, surface_distance
from .grid import choose_resolution, estimated_bytes
from .mesh import signed_volume
from .model import SkinResult
from .raster import rasterize
from .resources import worker_memory_limit, memory_metrics
from .settings import resolved_solver_distances, settings_payload, settings_percentages
from .status import check_cancelled, report
from ..warm_start.signatures import (
    geometry_state_hash, solver_settings_hash, source_connectivity_signature,
    source_identity_signature, structural_signature,
)
from ..warm_start.invalidation import source_contact_signature


def solve_capture(capture, progress=None, cancelled=None):
    started = time.perf_counter(); check_cancelled(cancelled)
    resolution, grid, distances, fields = _prepare_capture(capture, progress, cancelled)
    origin, dimensions, voxel = grid
    result, binding, quality = reconstruct(capture, fields, origin, voxel, distances, progress, cancelled)
    stats = _statistics(capture, result, dimensions, voxel, resolution, distances, started)
    _finish_binding_statistics(stats, quality)
    stats.update(memory_metrics())
    from ..mesh_diagnostics import check_result
    return annotate(check_result(SkinResult(result[0], result[1], result[2], stats, result[3], binding), cancelled), "skin")


def _prepare_capture(capture, progress, cancelled):
    vertices, faces, scp_faces, collagen = combine_capture(capture)
    length = float(np.max(capture.upper - capture.lower))
    distances = resolved_solver_distances(capture.settings, length)
    resolution, grid = choose_resolution(vertices, worker_memory_limit(), capture.resolution, capture.settings)
    origin, dimensions, voxel = grid
    _preflight(dimensions, vertices, faces)
    required, full, collagen_grid = _build_fields(
        vertices, faces, scp_faces, collagen, origin, dimensions, voxel, distances, progress, cancelled
    )
    return resolution, grid, distances, (required, full, collagen_grid)


def _finish_binding_statistics(statistics, quality):
    from ..diagnostic_checks import merge
    merge(statistics, quality)
    _check_binding_quality(quality, statistics)


def _check_binding_quality(quality, statistics):
    unbound = float(quality["unbound_percent"])
    if unbound > 5.0:
        statistics.setdefault("warnings", []).append(f"Draft-skin binding is incomplete for {unbound:.2f}% of vertices.")
    if quality["visibility_rejected_percent"] > 5.0:
        statistics.setdefault("warnings", []).append("Some draft-skin bindings have weak source visibility.")
    if quality["ambiguous_percent"] > 25.0:
        statistics.setdefault("warnings", []).append("Draft-skin bindings contain broad ambiguous support.")


def combine_capture(capture):
    vertex_blocks = [np.asarray(item.vertices, dtype=np.float64) for item in capture.sources]
    offsets = np.asarray([0, *np.cumsum([len(item) for item in vertex_blocks])], dtype=np.int64)
    vertices = np.concatenate(vertex_blocks)
    faces = np.concatenate([item.triangles + offsets[i] for i, item in enumerate(capture.sources)]).astype(np.int32)
    scp_faces = _scp_face_subset(capture, offsets)
    collagen = np.concatenate([_source_values(item) for item in capture.sources])
    return vertices, faces, scp_faces, collagen


def _scp_face_subset(capture, offsets):
    blocks = [
        item.triangles + offsets[index]
        for index, item in enumerate(capture.sources)
        if item.entity_type == "SCP"
    ]
    return np.concatenate(blocks).astype(np.int32)


def _source_values(source):
    if source.entity_type != "SCP" or source.collagen is None:
        return np.ones(len(source.vertices), dtype=np.float32)
    return np.asarray(source.collagen, dtype=np.float32)


def _preflight(dimensions, vertices, faces):
    if not len(vertices) or not len(faces):
        raise ValueError("Draft skin has no source geometry.")
    if estimated_bytes(dimensions) > worker_memory_limit():
        raise MemoryError("Draft skin grid exceeds the safe worker memory limit.")


def _build_fields(vertices, faces, scp_faces, values, origin, dimensions, voxel, distances, progress, cancelled):
    report(progress, "Rasterizing", 0.06, "Rasterizing all contributors")
    all_surface, _unused = rasterize(vertices, faces, origin, dimensions, voxel, cancelled=cancelled)
    report(progress, "Rasterizing", 0.22, "Rasterizing SCP collagen sources")
    scp_surface, seeds = rasterize(vertices, scp_faces, origin, dimensions, voxel, values, cancelled=cancelled)
    required = _required_field(all_surface, voxel, distances, progress, cancelled)
    full = _rest_field(scp_surface, required, voxel, distances, progress, cancelled)
    collagen = _collagen(scp_surface, seeds, voxel, distances, progress, cancelled)
    return required, full, collagen


def _required_field(surface, voxel, distances, progress, cancelled):
    check_cancelled(cancelled)
    report(progress, "Required envelope", 0.36, "Building SCP and VCP envelope")
    distance = surface_distance(surface, voxel)
    return exterior_field(distance, voxel, distances["required_probe"], distances["required_offset"])


def _rest_field(surface, required, voxel, distances, progress, cancelled):
    check_cancelled(cancelled)
    report(progress, "Rest envelope", 0.52, "Building SCP collagen envelope")
    distance = surface_distance(surface, voxel)
    rest = exterior_field(distance, voxel, distances["rest_probe"], distances["rest_offset"])
    return smooth_max(rest, required, distances["blend_radius"])


def _collagen(surface, seeds, voxel, distances, progress, cancelled):
    report(progress, "Collagen field", 0.65, "Propagating variable collagen")
    callback = lambda value: report(progress, "Collagen field", 0.65 + (0.12 * value))
    return collagen_field(
        surface, seeds, voxel, distances["collagen_inner"], distances["collagen_outer"], callback, cancelled
    )


def _statistics(capture, result, dimensions, voxel, resolution, distances, started):
    vertices, faces, collagen, validation = result
    stats = _geometry_statistics(vertices, faces, collagen, dimensions, voxel)
    stats.update(_run_statistics(capture, validation, resolution, started))
    stats.update(_settings_statistics(capture, distances))
    stats.update(_binding_signatures(capture, vertices, faces))
    return stats


def _binding_signatures(capture, vertices, faces):
    return {"structural_signature": structural_signature(len(vertices), faces),
            "source_identity_signature": source_identity_signature(capture.sources),
            "source_connectivity_signature": source_connectivity_signature(capture.sources),
            "source_contact_signature": source_contact_signature(capture.sources),
            "geometry_state_hash": geometry_state_hash(capture.sources),
            "solver_settings_hash": solver_settings_hash(capture.settings),
            "gap_settings_signature": gap_signature(capture)}


def _run_statistics(capture, validation, resolution, started):
    return {
        "root_name": capture.root_name, "input_hash": capture.input_hash,
        "solver_version": SOLVER_VERSION, "sources": len(capture.sources),
        "resolution": int(resolution), "elapsed_seconds": time.perf_counter() - started,
        "warnings": list(capture.warnings), "validation": validation.message if validation is not None else "Quality unknown",
        "source_map": _source_map(capture),
    }


def _settings_statistics(capture, distances):
    return {
        "settings": settings_payload(capture.settings),
        "settings_percent": settings_percentages(capture.settings),
        "resolved_distances": {key: float(value) for key, value in distances.items()},
    }


def _geometry_statistics(vertices, faces, collagen, dimensions, voxel):
    return {
        "vertices": len(vertices),
        "triangles": len(faces),
        "volume": signed_volume(vertices, faces),
        "collagen_mean": float(np.mean(collagen)),
        "grid_dimensions": list(dimensions),
        "voxel_size": float(voxel),
    }


def _source_map(capture):
    return [
        {
            "source_index": item.source_index,
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "mirror_role": item.mirror_role,
            "object_name": item.object_name,
            "gap_limit_ratio": effective_gap(item, capture.settings)[0],
            "gap_strength": effective_gap(item, capture.settings)[1],
        }
        for item in capture.sources
    ]

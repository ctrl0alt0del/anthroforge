import time

import numpy as np

from .constants import BLEND_RADIUS, REQUIRED_OFFSET, REQUIRED_PROBE, REST_OFFSET, REST_PROBE, SOLVER_VERSION
from .fields import collagen_field, exterior_field, smooth_max, surface_distance
from .grid import choose_resolution, estimated_bytes
from .mesh import extract_mesh, largest_component, orient_outward, sample_grid, signed_volume, smooth_mesh
from .model import SkinResult
from .raster import rasterize
from .resources import worker_memory_limit
from .status import check_cancelled, report
from .validation import validate_mesh


def solve_capture(capture, progress=None, cancelled=None):
    started = time.perf_counter()
    vertices, faces, scp_faces, collagen = combine_capture(capture)
    resolution, grid = choose_resolution(vertices, worker_memory_limit(), capture.resolution)
    origin, dimensions, voxel = grid
    _preflight(dimensions, vertices, faces)
    required, full, collagen_grid = _build_fields(
        vertices, faces, scp_faces, collagen, origin, dimensions, voxel, progress, cancelled
    )
    result = _extract_result(required, full, collagen_grid, vertices, origin, voxel, progress, cancelled)
    stats = _statistics(capture, result, dimensions, voxel, resolution, started)
    return SkinResult(result[0], result[1], result[2], stats, result[3])


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


def _build_fields(vertices, faces, scp_faces, values, origin, dimensions, voxel, progress, cancelled):
    report(progress, "Rasterizing", 0.06, "Rasterizing all contributors")
    all_surface, _unused = rasterize(vertices, faces, origin, dimensions, voxel, cancelled=cancelled)
    report(progress, "Rasterizing", 0.22, "Rasterizing SCP collagen sources")
    scp_surface, seeds = rasterize(vertices, scp_faces, origin, dimensions, voxel, values, cancelled=cancelled)
    required = _required_field(all_surface, voxel, progress, cancelled)
    full = _rest_field(scp_surface, required, voxel, progress, cancelled)
    collagen = _collagen(scp_surface, seeds, voxel, progress, cancelled)
    return required, full, collagen


def _required_field(surface, voxel, progress, cancelled):
    check_cancelled(cancelled)
    report(progress, "Required envelope", 0.36, "Building SCP and VCP envelope")
    distance = surface_distance(surface, voxel)
    return exterior_field(distance, voxel, REQUIRED_PROBE, REQUIRED_OFFSET)


def _rest_field(surface, required, voxel, progress, cancelled):
    check_cancelled(cancelled)
    report(progress, "Rest envelope", 0.52, "Building SCP collagen envelope")
    distance = surface_distance(surface, voxel)
    rest = exterior_field(distance, voxel, REST_PROBE, REST_OFFSET)
    return smooth_max(rest, required, BLEND_RADIUS * voxel)


def _collagen(surface, seeds, voxel, progress, cancelled):
    report(progress, "Collagen field", 0.65, "Propagating variable collagen")
    callback = lambda value: report(progress, "Collagen field", 0.65 + (0.12 * value))
    return collagen_field(surface, seeds, voxel, callback, cancelled)


def _extract_result(required, full, collagen, sources, origin, voxel, progress, cancelled):
    check_cancelled(cancelled)
    field = required + (collagen * (full - required))
    report(progress, "Meshing", 0.79, "Extracting draft skin")
    vertices, faces = extract_mesh(field, origin, voxel)
    vertices, faces = largest_component(vertices, faces)
    vertices = _smooth(vertices, faces, progress, cancelled)
    faces = orient_outward(vertices, faces)
    values = sample_grid(collagen, vertices, origin, voxel)
    inside = _sources_inside(field, sources, origin, voxel)
    validation = validate_mesh(vertices, faces, inside, cancelled)
    if not validation.valid:
        raise ValueError(validation.message)
    return vertices, faces, values, validation


def _smooth(vertices, faces, progress, cancelled):
    report(progress, "Finishing", 0.86, "Smoothing extracted surface")
    callback = lambda value: report(progress, "Finishing", 0.86 + (0.08 * value))
    return smooth_mesh(vertices, faces, callback, cancelled)


def _sources_inside(field, vertices, origin, voxel):
    values = sample_grid(field, vertices, origin, voxel)
    return bool(np.all(values >= (-1.5 * voxel)))


def _statistics(capture, result, dimensions, voxel, resolution, started):
    vertices, faces, collagen, validation = result
    stats = _geometry_statistics(vertices, faces, collagen, dimensions, voxel)
    stats.update({
        "root_name": capture.root_name,
        "input_hash": capture.input_hash,
        "solver_version": SOLVER_VERSION,
        "sources": len(capture.sources),
        "resolution": int(resolution),
        "elapsed_seconds": time.perf_counter() - started,
        "warnings": list(capture.warnings),
        "validation": validation.message,
        "source_map": _source_map(capture),
    })
    return stats


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
        }
        for item in capture.sources
    ]

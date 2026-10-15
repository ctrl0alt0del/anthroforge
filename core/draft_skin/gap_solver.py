"""Native local gap reconstruction and validation orchestration."""
import numpy as np
from .gap_native import GapQueries
from .gap_tiles import SkinTiles, exterior_precision
from .gap_quality import validate, supported_components, source_intersections
from .gap_bindings import bind
from .mesh import orient_outward, sample_grid
from .resources import worker_memory_limit
from .status import check_cancelled, report
from ..diagnostic_checks import optional, merge, mesh_quality


def protected_grid(queries, field, origin, voxel, reach, progress, cancelled):
    width, count = exterior_precision(queries, field, origin, voxel, reach, progress, cancelled)
    fine = min(voxel, width/5.5) if count else voxel
    occupied = np.argwhere(field >= 0)
    if not len(occupied):
        raise ValueError("Draft skin has no occupied envelope.")
    low, high = occupied.min(0)-2, occupied.max(0)+2
    shape = np.ceil((high-low)*voxel/fine).astype(np.int64)+1
    if np.any(shape > 1048576):
        raise MemoryError("Unresolved gap precision: the required lattice exceeds supported dimensions.")
    return origin+low*voxel, shape, fine


def reconstruct(capture, fields, origin, voxel, distances, progress, cancelled):
    required, full, collagen = fields
    field = required+collagen*(full-required); reach = 3*distances['rest_probe']
    with GapQueries(capture) as queries:
        grid = protected_grid(queries, field, origin, voxel, reach, progress, cancelled)
        with SkinTiles(queries, field, origin, voxel, grid, reach, distances['rest_offset'],
                       worker_memory_limit(), progress, cancelled) as tiles:
            result, stats = finish(tiles, queries, progress, cancelled)
        check_cancelled(cancelled)
        binding, quality = _binding(result[0], queries, progress, cancelled)
        merge(stats, optional("source intersections", lambda: source_intersections(queries, progress, cancelled), cancelled))
    merge(stats, quality); stats['gap_voxel_size'] = float(grid[2])
    values = sample_grid(collagen, result[0], origin, voxel)
    return (result[0], result[1], values, result[2]), binding, stats


def finish(tiles, queries, progress, cancelled):
    report(progress, "Meshing", .88, "Extracting skin on a shared tile lattice")
    vertices, faces = tiles.mesh(cancelled)
    vertices, faces, removed = supported_components(vertices, faces, queries)
    vertices = tiles.smooth(vertices, faces, 8, progress, cancelled)
    stats = tiles.statistics(); tiles.release_field()
    faces = orient_outward(vertices, faces)
    merge(stats, optional("source coverage and gaps", lambda: tiles.validation(vertices, faces, progress, cancelled), cancelled))
    covered = not any(stats.get(k, 0) for k in ("source_vertices_outside", "source_triangles_crossed", "protected_gap_violations"))
    validation, quality = mesh_quality(vertices, faces, covered, cancelled)
    merge(stats, quality); stats['unsupported_components_removed'] = removed
    return (vertices, faces, validation), stats


def require_coverage(stats):
    exposed = int(stats.get('source_vertices_outside', 0))
    crossed = int(stats.get('source_triangles_crossed', 0))
    gaps = int(stats.get('protected_gap_violations', 0))
    if exposed or crossed or gaps:
        raise ValueError(f"Draft skin validation failed: {exposed} exposed source vertices, "
                         f"{crossed} source intersections, {gaps} unresolved protected gaps. Previous output retained.")


def _binding(vertices, queries, progress, cancelled):
    value = optional("skin binding", lambda: bind(vertices, queries, progress, cancelled), cancelled)
    if isinstance(value, dict):
        value.update(unbound_percent=100., visibility_rejected_percent=0., ambiguous_percent=0.)
        return None, value
    return value

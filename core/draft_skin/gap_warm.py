"""Validate deformed skin against freshly captured source surfaces and gap policies."""
from .gap_native import GapQueries
from .gap_tiles import SkinTiles
from .gap_solver import protected_grid
from .gap_quality import validate
from .resources import worker_memory_limit


def revalidate(capture, vertices, faces, progress=None, cancelled=None):
    from .solver import _prepare_capture
    _, (origin, _, voxel), distances, fields = _prepare_capture(capture, progress, cancelled)
    required, full, collagen = fields
    field = required+collagen*(full-required); reach = 3*distances['rest_probe']
    with GapQueries(capture) as queries:
        grid = protected_grid(queries, field, origin, voxel, reach, progress, cancelled)
        with SkinTiles(queries, field, origin, voxel, grid, reach, distances['rest_offset'],
                       worker_memory_limit(), progress, cancelled) as tiles:
            stats = tiles.statistics(); tiles.release_field()
            stats.update(tiles.validation(vertices, faces, progress, cancelled))
    valid = not any(stats[name] for name in ('source_vertices_outside', 'source_triangles_crossed', 'protected_gap_violations'))
    report, quality = validate(vertices, faces, valid)
    stats.update(quality, gap_voxel_size=float(grid[2]), gaps_revalidated=True)
    return report, stats

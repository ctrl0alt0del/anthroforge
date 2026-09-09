"""Persistent material topology for native Blender surface recomputation."""
import numpy as np
from .codec import decode
from .inflation import material_loft, faces, inflate
from .errors import require


def surface(rows, raw, resolver=None):
    from ..vcp.fiber_surface import FiberSurfaceResult
    material = decode(raw)
    require(len(rows) == len(material["u"]), "MATERIAL_FIBER_COUNT_CHANGED")
    require(len(rows) == len(material["row_s"]) and all(len(row) == len(s) for row,s in zip(rows,material["row_s"])),
            "MATERIAL_NODE_COUNT_CHANGED")
    grid, u = material_loft(rows, material["row_s"], material["u"], material["s"], material["closed"])
    grid,u = conform_native(grid,u,material,resolver)
    topology = faces(len(u), len(material["s"]), material["closed"])
    return FiberSurfaceResult(tuple(map(tuple, grid.reshape(-1, 3))), tuple(map(tuple, topology)),
                              tuple(tuple(map(tuple, row)) for row in grid), material["closed"])


def conform_native(grid,u,material,resolver):
    from . import conformance
    if "boundary_document" not in material:
        return grid,u
    require(resolver is not None, "BOUNDARY_RESOLVER_REQUIRED")
    document,name,dense = material["boundary_document"],material["muscle_name"],material["grid_u"]
    required = conformance.samples(document,name,resolver,dense)
    require(len(required) == len(dense), "BOUNDARY_REBUILD_REQUIRED", "Rebuild the authoring document to refine changed boundaries")
    grid = conformance.resample(grid,u,dense)
    return conformance.apply(grid,dense,material["s"],document,name,resolver,False)


def numeric(request):
    from ..vcp.muscle_numeric import _valid_result
    material = decode(request.spec.authoring_material)
    config = settings(material["config"], request.spec)
    grid = request.points
    if request.spec.initialize_control:
        config["control_world"] = grid[len(grid)//2,len(grid[0])//2]
    require(grid.shape[:2] == (len(material["u"]), len(material["s"])), "MATERIAL_GRID_CHANGED")
    inflated = inflate(grid, material["u"], material["s"], config, material["closed"])
    topology = faces(len(grid), len(grid[0]), material["closed"])
    return _valid_result(request.muscle_id, grid, inflated, topology)


def settings(config, spec):
    result = dict(config, enabled=spec.inflation_enabled, amount=spec.inflation_max_value,
                  mode="control_point" if spec.inflation_mode == "CTRL_POINT" else "distributed",
                  flip_normals=spec.flip_normals, radius=spec.inflation_falloff_radius,
                  direction_depth=spec.inflation_direction_depth, falloff=spec.inflation_falloff_type.lower(),
                  control_world=spec.control_world, length_taper=spec.inflation_length_taper_band)
    result["boundary"] = dict(config["boundary"], strength=spec.inflation_boundary_strength,
                              power=spec.inflation_boundary_power, along=spec.authoring_boundary_along,
                              across=spec.authoring_boundary_across)
    if result["boundary"]["along"] == 0:
        result["length_taper"] = 0
    return result


def mixed_batch(requests, backend):
    from ..vcp.muscle_numeric import execute_muscle_batch, MuscleNumericBatchResult, _invalid_result
    legacy = execute_muscle_batch([r for r in requests if not r.spec.authoring_material], backend)
    results, remaining = [], iter(legacy.results)
    for request in requests:
        try:
            results.append(numeric(request) if request.spec.authoring_material else next(remaining))
        except (ValueError, KeyError) as error:
            results.append(_invalid_result(request.muscle_id, str(error)))
    return MuscleNumericBatchResult(tuple(results), "MATERIAL_NUMPY+" + legacy.backend, legacy.elapsed_ms)

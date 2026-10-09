"""Capture branch roots through shared authored identity and cached solved routes."""
import numpy as np
from ..vcp.branched_surface import BranchInput, prepare_assembly
from ..vcp.shared_point_storage import slots, point_record
from .muscle_sync_runtime import collect_fiber_points
from ..vcp.free_path import is_free, decode, point_indices
from ..vcp.free_surface_stations import resolve


def source_surface(root, key):
    result = next((s for s in root.af_vcp_system.fiber_surfaces if s.id == key), None)
    if result is None:
        raise ValueError("Missing source Fiber Surface: " + key)
    if result.construction_mode != "LOFT" or result.close_across_fibers or result.use_mirrored_rows:
        raise ValueError("Branches require open source lofts; nested branches and mirrored rows are unsupported")
    return result


def source_fibers(root, surface):
    lookup = {f.id: f for f in root.af_vcp_system.fibers}
    fibers = [lookup.get(ref.fiber_id) for ref in surface.fiber_refs]
    if len(fibers) < 2 or any(f is None or f.topology_mode != "OPEN" for f in fibers):
        raise ValueError("Branching requires at least two open fibers in each loft")
    return fibers


def capture_assembly(root, scene, surface):
    main_surface = source_surface(root, surface.main_surface_id)
    fibers = source_fibers(root, main_surface)
    routes = collect_fiber_points(root, scene, fibers)
    if not routes:
        raise ValueError("Main solved fibers are unavailable")
    branches = tuple(_branch_input(root, scene, fibers, routes, c) for c in surface.branches)
    _free_budget(root, surface, routes, branches)
    from .geometry_instance import active
    return prepare_assembly(routes, branches, surface.flip_normals != active(), main_stations=resolve(main_surface, fibers))


def _free_budget(root, surface, routes, branches):
    sources = [source_surface(root, surface.main_surface_id)] + [source_surface(root, b.surface_id) for b in surface.branches]
    if any(is_free(f) for source in sources for f in source_fibers(root, source)):
        from ..vcp.free_surface import branch_budget
        branch_budget(routes, branches, multiplier=4)


def _branch_input(root, scene, fibers, routes, connection):
    boundary = _boundary(fibers, connection.boundary_fiber_id)
    branch = source_surface(root, connection.surface_id)
    children = source_fibers(root, branch)
    root_ids = tuple(ref.point_id for ref in connection.roots)
    if len(root_ids) != len(children):
        raise ValueError("Every branch fiber requires a shared root point")
    child_routes = collect_fiber_points(root, scene, children)
    if not child_routes:
        raise ValueError("Branch solved fibers are unavailable")
    indices = _root_indices(root, scene, fibers[boundary], routes[boundary], root_ids)
    ordered = _oriented_children(children, child_routes, root_ids)
    stations = _oriented_stations(branch, children, root_ids)
    return BranchInput(connection.id, boundary, indices, ordered, connection.width, connection.fullness, stations)


def _oriented_stations(surface, fibers, keys):
    values = resolve(surface, fibers)
    return tuple(s if f.a_point_id == key else (np.asarray(s)[-1]+np.asarray(s)[0]-np.asarray(s)[::-1]).tolist()
                 for f, s, key in zip(fibers, values, keys))


def _boundary(fibers, key):
    if fibers[0].id == key:
        return 0
    if fibers[-1].id == key:
        return -1
    raise ValueError("Branch must use an outer main fiber")


def _root_indices(root, scene, fiber, route, keys):
    if is_free(fiber): return point_indices(decode(fiber.free_path_json), keys)
    from ..vcp.fiber_node_attachment import _anchor_specs, _open_pin_indices
    from ..vcp.attachment_backend import attachment_runtime
    from .geometry_instance import active
    from ..vcp.fiber_instance import MirroredFiber
    if active(): fiber = MirroredFiber(fiber)
    specs = _anchor_specs(root, scene, fiber, attachment_runtime(scene, None))
    occurrences = slots(fiber)
    if len(specs) != len(occurrences):
        raise ValueError("Unresolved main authored points")
    indices = _open_pin_indices(route, tuple(row[2] for row in specs))
    mapping = {getattr(owner, slot): int(index) for (owner, slot, _), index in zip(occurrences, indices)}
    if any(key not in mapping for key in keys):
        raise ValueError("Branch root is not an authored point of the main boundary fiber")
    return tuple(mapping[key] for key in keys)


def _oriented_children(fibers, routes, keys):
    result = []
    for fiber, route, key in zip(fibers, routes, keys):
        if fiber.a_point_id == key:
            result.append(np.asarray(route, dtype=float))
        elif fiber.b_point_id == key:
            result.append(np.asarray(route[::-1], dtype=float))
        else:
            raise ValueError("Branch endpoint must reference its explicit shared root")
    return tuple(result)

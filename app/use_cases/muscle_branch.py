"""Explicit branch connections shared by UI and authoring; source lofts are retained."""
from uuid import uuid4
from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates, vcp_prop_updates_suppressed
from ...core.vcp.shared_point_storage import slots, ensure_point
from ...core.visualization.branched_surface_capture import source_surface, source_fibers, _boundary
from .fiber_surface_create import _new_surface


def find_muscle(root, key):
    return next(m for m in root.af_vcp_system.muscles if m.id == key)


def muscle_surface(root, muscle):
    if muscle.surface_source_mode != "FIBER_SURFACE":
        raise ValueError("Convert the muscle to a Fiber Surface before adding branches")
    return next(s for s in root.af_vcp_system.fiber_surfaces if s.id == muscle.fiber_surface_id)


def add_branch(root, muscle_id, branch_surface_id, boundary_id, point_ids):
    muscle = find_muscle(root, muscle_id)
    current = muscle_surface(root, muscle)
    main_id = current.main_surface_id if current.construction_mode == "BRANCHED_LOFT" else current.id
    main, branch = source_surface(root, main_id), source_surface(root, branch_surface_id)
    children, roots = _validate_add(root, current, main, branch, boundary_id, tuple(point_ids))
    with suppress_vcp_prop_updates():
        wrapper = current if current.construction_mode == "BRANCHED_LOFT" else _wrap(root, muscle, main)
        connection = _new_connection(wrapper, muscle, branch, boundary_id, point_ids)
        for child, point in zip(children, roots):
            child.a_point_id = point.id
        refresh_wrapper_refs(root, wrapper)
    _dirty(root, muscle, {f.id for f in children})
    return connection


def _validate_add(root, current, main, branch, boundary_id, point_ids):
    if main.id == branch.id or any(c.surface_id == branch.id for c in getattr(current, "branches", ())):
        raise ValueError("Each branch needs a separate source loft")
    parents, children = source_fibers(root, main), source_fibers(root, branch)
    boundary = parents[_boundary(parents, boundary_id)]
    if set(f.id for f in parents) & set(f.id for f in children):
        raise ValueError("Branch fibers must be distinct from main fibers")
    occurrences = slots(boundary)
    keys = [ensure_point(owner, slot).id for owner, slot, _ in occurrences]
    indices = [keys.index(key) for key in point_ids]
    _validate_interval(current, boundary_id, keys, indices, len(children))
    lookup = {p.id: p for p in root.af_vcp_system.authored_points}
    return children, [lookup[key] for key in point_ids]


def _validate_interval(current, boundary_id, keys, indices, count):
    if len(indices) != count or len(indices) < 2 or indices != sorted(set(indices)):
        raise ValueError("Select one ordered, distinct main point per branch fiber")
    if indices[0] == 0 or indices[-1] == len(keys)-1:
        raise ValueError("Branch roots must be main midpoints, not its endpoints")
    for connection in getattr(current, "branches", ()):
        if connection.boundary_fiber_id != boundary_id:
            continue
        occupied = [keys.index(r.point_id) for r in connection.roots]
        if indices[0] <= occupied[-1] and indices[-1] >= occupied[0]:
            raise ValueError("Branch intervals cannot overlap or share endpoints")


def _wrap(root, muscle, main):
    wrapper = _new_surface(root.af_vcp_system, main.name + " branches", "BRANCHED_LOFT", False, False)
    wrapper.main_surface_id, wrapper.flip_normals = main.id, main.flip_normals
    muscle.fiber_surface_id = wrapper.id
    return wrapper


def _new_connection(wrapper, muscle, branch, boundary_id, point_ids):
    from ...core.importing.rna import scalar_dict, apply_scalar_dict
    connection = wrapper.branches.add()
    connection.id, connection.surface_id = str(uuid4()), branch.id
    connection.boundary_fiber_id = boundary_id
    for key in point_ids:
        connection.roots.add().point_id = key
    apply_scalar_dict(connection.settings, scalar_dict(muscle))
    connection.settings.id = muscle.id
    wrapper.active_branch_index = len(wrapper.branches)-1
    return connection


def refresh_wrapper_refs(root, wrapper):
    ids = (wrapper.main_surface_id, *(b.surface_id for b in wrapper.branches))
    keys = dict.fromkeys(ref.fiber_id for key in ids for ref in source_surface(root, key).fiber_refs)
    wrapper.fiber_refs.clear()
    for key in keys:
        wrapper.fiber_refs.add().fiber_id = key


def remove_branch(root, muscle_id, connection_id):
    muscle = find_muscle(root, muscle_id)
    wrapper = muscle_surface(root, muscle)
    index = next(i for i, c in enumerate(wrapper.branches) if c.id == connection_id)
    with suppress_vcp_prop_updates():
        wrapper.branches.remove(index)
        wrapper.active_branch_index = min(index, len(wrapper.branches)-1)
        refresh_wrapper_refs(root, wrapper)
        if not wrapper.branches:
            wrapper.construction_mode = "LOFT"
            wrapper.main_surface_id = ""
    _dirty(root, muscle, set())


def _remove_wrapper(root, key):
    surfaces = root.af_vcp_system.fiber_surfaces
    index = next(i for i, s in enumerate(surfaces) if s.id == key)
    surfaces.remove(index)


def _dirty(root, muscle, fibers):
    if vcp_prop_updates_suppressed():
        return
    from ...app.runtime_api import schedule_context
    from ...core.deps.dirty_hints import dirty_hints_for
    import bpy
    kind, ids = ("FIBER", fibers) if fibers else ("MUSCLE", {muscle.id})
    schedule_context(bpy.context, dirty_hints=dirty_hints_for(kind, ids), event_type="FIBER_UPDATE" if fibers else "MUSCLE_UPDATE")


def protected_references(root):
    protected = set()
    for surface in root.af_vcp_system.fiber_surfaces:
        for connection in surface.branches:
            roots = {ref.point_id for ref in connection.roots}
            for fiber in source_fibers(root, source_surface(root, connection.surface_id)):
                protected.update((fiber.id, i) for i, (owner, slot, _) in enumerate(slots(fiber))
                                 if getattr(owner, slot) in roots)
            boundary = next(f for f in root.af_vcp_system.fibers if f.id == connection.boundary_fiber_id)
            protected.update((boundary.id, i) for i, (owner, slot, _) in enumerate(slots(boundary))
                             if getattr(owner, slot) in roots)
    return protected


def detach_point(root, fiber_id, index):
    if (fiber_id, index) in protected_references(root):
        raise ValueError("Remove the branch connection before detaching its root")
    fiber = next(f for f in root.af_vcp_system.fibers if f.id == fiber_id)
    owner, slot, role = slots(fiber)[index]
    original = ensure_point(owner, slot)
    if role != "MID" and original.normal_offset:
        raise ValueError("Rebind the offset junction endpoint to the surface before detaching")
    with suppress_vcp_prop_updates():
        copy = root.af_vcp_system.authored_points.add()
        copy.id, copy.parent_id, copy.attach_param = str(uuid4()), original.parent_id, original.attach_param
        copy.normal_offset = original.normal_offset
        setattr(owner, slot, copy.id)
    return copy.id

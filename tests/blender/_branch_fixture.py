"""Native cube fixture with explicit cached surface routes and no experiment dependency."""
import bpy
from mathutils import Vector
from _helpers import root, scp_with_object
from anthroforge.app.use_cases.fiber_create import _new_fiber
from anthroforge.app.use_cases.fiber_surface_create import _new_surface, _assign_refs
from anthroforge.app.use_cases.muscle_create import _new_muscle
from anthroforge.app.use_cases.muscle_branch import add_branch
from anthroforge.core.vcp.fiber_pin_snapping import capture_attachment_from_world
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.visualization.fiber_sync import register_fiber_sync


def _route(points, steps=16):
    vectors = [Vector(p) for p in points]
    return [a.lerp(b, i/steps) for a, b in zip(vectors, vectors[1:]) for i in range(steps)] + [vectors[-1]]


def _fiber(r, scp, anchors, path):
    raws = [capture_attachment_from_world(r, bpy.context.scene, scp.id, Vector(p)) for p in anchors]
    fiber = _new_fiber(r, scp.id, scp.id, raws[0], raws[-1], [(scp.id, raw) for raw in raws[1:-1]])
    points = _route(path)
    fiber.node_count, fiber.solver_version = len(points), 3
    register_fiber_sync().apply_points(r, bpy.context.scene, fiber, points, commit=True)
    return fiber


def _main(r, scp, x, middle):
    start, end = (x, -1.5, -2), (x, -1.5, 2)
    first, last = (x, -2, -.75), (x, -2, .75)
    anchors = [start, first, last, end] if middle else [start, end]
    return _fiber(r, scp, anchors, [start, (x, -2, -2), first, last, (x, -2, 2), end])


def _branch(r, scp, z):
    start, end = (.75, -2, z), (2, .75, z)
    return _fiber(r, scp, [start, end], [start, (2, -2, z), end])


def create_fixture():
    r = root()
    bpy.ops.mesh.primitive_cube_add(size=4)
    scp = scp_with_object(r, 'Branch cube', bpy.context.object)
    bpy.context.view_layer.update()
    with suppress_vcp_prop_updates():
        a, b = _main(r, scp, .75, True), _main(r, scp, -.75, False)
        c, d = _branch(r, scp, -.75), _branch(r, scp, .75)
        main, branch = _surfaces(r, (b, a), (c, d))
        muscle = _new_muscle(r.af_vcp_system, 'Native branched muscle', False, False)
        muscle.surface_source_mode, muscle.fiber_surface_id = 'FIBER_SURFACE', main.id
        muscle.inflation_mode, muscle.inflation_max_value = 'DISTRIBUTED', .2
        connection = add_branch(r, muscle.id, branch.id, a.id, [p.point_id for p in a.mid_touches])
    return r, muscle, connection, (a, b, c, d)


def _surfaces(r, main_fibers, branch_fibers):
    main = _new_surface(r.af_vcp_system, 'Main loft', 'LOFT', False, False)
    branch = _new_surface(r.af_vcp_system, 'Branch loft', 'LOFT', False, False)
    _assign_refs(main, [f.id for f in main_fibers]); _assign_refs(branch, [f.id for f in branch_fibers])
    return main, branch

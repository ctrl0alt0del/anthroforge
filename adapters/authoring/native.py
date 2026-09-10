"""Explicit-input native entity writer; never reads viewport selection."""
from mathutils import Vector
from ...app.use_cases.fiber_create import _new_fiber, _new_loop_fiber
from ...app.use_cases.fiber_surface_create import _new_surface, _assign_refs
from ...app.use_cases.muscle_create import _new_muscle
from ...core.vcp.fiber_node_attachment import capture_fiber_node_attachments
from ...core.visualization.fiber_sync import register_fiber_sync
from ...core.authoring.errors import require
from .volume import configure
from .attachments import capture, normal_offset


def attachment(root, scene, anchor):
    raw = capture(root, scene, anchor)
    require(raw is not None, "ATTACHMENT_CAPTURE_FAILED", anchor["owner"])
    return anchor["owner"], raw


def write_fiber(root, scene, row, existing=None):
    specs = [attachment(root, scene, a) for a in row["anchors"]]
    fiber = existing or (_new_loop_fiber(root, specs) if row["closed"] else _new_fiber(root, *open_args(specs)))
    set_anchors(fiber, row, specs, root, scene)
    fiber.node_count, fiber.solver_version = len(row["points"]), 3
    fiber.name = row["id"]
    fiber["af_authoring_symmetry"] = "explicit"
    points = [Vector(p) for p in row["points"]]
    register_fiber_sync().apply_points(root, scene, fiber, points, commit=True)
    captured = capture_fiber_node_attachments(root, scene, fiber, points)
    require(captured.ok, 'ATTACHMENT_CAPTURE_FAILED', captured.error)
    return fiber


def open_args(specs):
    return specs[0][0], specs[-1][0], specs[0][1], specs[-1][1], specs[1:-1]


def set_anchors(fiber, row, specs, root, scene):
    fiber.loop_anchors.clear()
    fiber.mid_touches.clear()
    fiber.topology_mode = "LOOP" if row["closed"] else "OPEN"
    if not row["closed"]:
        fiber.a_parent_id, fiber.a_attach_param = specs[0]
        fiber.b_parent_id, fiber.b_attach_param = specs[-1]
    indices = range(len(specs)) if row["closed"] else range(1, len(specs)-1)
    for index in indices:
        item = (fiber.loop_anchors if row["closed"] else fiber.mid_touches).add()
        item.parent_id, item.attach_param = specs[index]
        if not row["closed"]:
            item.normal_offset = normal_offset(root, scene, specs[index][0], row["anchors"][index]["offset"])


def write_muscle(root, scene, name, output, previous, document=None):
    vcp = root.af_vcp_system
    fibers = [str(write_fiber(root, scene, row, find(vcp.fibers, previous.get("fibers", {}).get(row["id"]))).id) for row in output["fibers"]]
    surface = find(vcp.fiber_surfaces, previous.get("surface")) or _new_surface(vcp, name, "LOFT", False, False)
    surface.fiber_refs.clear()
    _assign_refs(surface, fibers)
    surface.pop('af_authoring_material', None)
    muscle = find(vcp.muscles, previous.get("muscle")) or _new_muscle(vcp, name, False, False)
    muscle.surface_source_mode, muscle.fiber_surface_id = "FIBER_SURFACE", surface.id
    configure(muscle, output)
    return dict(muscle=muscle.id, surface=surface.id, fibers={row["id"]: f for row, f in zip(output["fibers"], fibers)})


def find(collection, identity):
    return next((item for item in collection if item.id == identity), None)

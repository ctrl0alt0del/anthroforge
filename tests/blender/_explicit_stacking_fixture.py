"""Native Free lofts with a transverse base intersection and stationary attachments."""
import numpy as np
import bpy
from _stacking_fixture import fixture


def crossing_fixture():
    from mathutils import Vector
    from anthroforge.app.use_cases.free_fiber import payload_for_points, commit
    from anthroforge.core.visualization.free_fiber_runtime import current
    root, under, cover = fixture()
    source = next(s for s in root.af_vcp_system.fiber_surfaces if s.id == cover.fiber_surface_id)
    ids = {r.fiber_id for r in source.fiber_refs}
    for fiber in root.af_vcp_system.fibers:
        if fiber.id not in ids: continue
        _, points = current(root, bpy.context.scene, fiber)
        values = [Vector((p.x, p.y, .18*np.sin(np.pi*p.x/2)**2)) for p in points]
        commit(root, bpy.context.scene, fiber, payload_for_points(root, bpy.context.scene, fiber, values), values)
    return root, under, cover

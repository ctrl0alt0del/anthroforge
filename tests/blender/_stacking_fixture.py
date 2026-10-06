"""Two native muscles with interior support and protected perimeter attachments."""
import bpy
from _helpers import root, fiber as new_fiber, capture_mesh_attachment
from _profile_fixture import _anchor
from anthroforge.app.use_cases.fiber_surface_create import create_native_muscle
from anthroforge.core.authoring.profile_config import wire
from anthroforge.core.vcp.muscle_section_profile import reset_profile


def fiber(owner, name, bounds, y, z):
    from mathutils import Vector
    from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
    from anthroforge.core.visualization.fiber_sync import register_fiber_sync
    from anthroforge.app.use_cases.free_fiber import configure_mode
    objects = [_anchor(owner, name+str(i), (x, y, z)) for i, x in enumerate(bounds)]
    anchors = [next(s for s in owner.af_scp_system.scps if s.geometry_object_ref == o) for o in objects]
    bpy.context.view_layer.update()
    with suppress_vcp_prop_updates():
        item = new_fiber(owner, anchors[0].id, anchors[1].id)
        item.a_attach_param, item.b_attach_param = (capture_mesh_attachment(owner, s, 0) for s in anchors)
    points = [Vector((bounds[0]+(bounds[1]-bounds[0])*i/16, y, z)) for i in range(17)]
    register_fiber_sync().apply_points(owner, bpy.context.scene, item, points); configure_mode(owner, bpy.context.scene, item, 'FREE')
    return next(o for o in bpy.context.scene.objects if o.get('af_fiber_proxy') and o.get('af_fiber_id') == item.id)


def muscle(owner, name, bounds, across, z, depth):
    proxies = [fiber(owner, name+str(i), bounds, y, z) for i, y in enumerate(across)]
    for obj in tuple(bpy.context.selected_objects): obj.select_set(False)
    for obj in proxies: obj.select_set(True)
    bpy.context.view_layer.objects.active = proxies[-1]; bpy.ops.af.create_fiber_surface()
    surface = owner.af_vcp_system.fiber_surfaces[-1]
    return create_native_muscle(owner, bpy.context.scene, surface.id, name, wire(reset_profile(depth)))


def fixture():
    owner = root()
    under = muscle(owner, 'Underlying', (.4, 1.6), (.35, .75), .10, .35)
    cover = muscle(owner, 'Covering', (0., 2.), (0., 1.1), 0., .05)
    return owner, under, cover

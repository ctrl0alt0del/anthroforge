"""Profile scenes use one canonical addon namespace and native operators."""
import bpy
from _helpers import root, mesh_object, scp_with_object


def _anchor(owner, name, position):
    obj = mesh_object(name, position)
    obj.scale = (.25, .25, .25)
    return scp_with_object(owner, name, obj).geometry_object_ref


def _fiber(owner, name, across):
    bpy.context.scene.af_new_fiber_origin_obj = _anchor(owner, name+'O', (0, across, 0))
    bpy.context.scene.af_new_fiber_insertion_obj = _anchor(owner, name+'I', (2, across, 0))
    bpy.ops.af.add_fiber_vcp()
    identity = owner.af_vcp_system.fibers[-1].id
    return next(obj for obj in bpy.context.scene.objects if obj.get('af_fiber_proxy') and obj.get('af_fiber_id') == identity)


def surface_only():
    owner = root()
    sources = (_fiber(owner, 'A', 0), _fiber(owner, 'B', 1))
    for obj in tuple(bpy.context.selected_objects):
        obj.select_set(False)
    for obj in sources:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = sources[-1]
    bpy.ops.af.create_fiber_surface()
    return owner, owner.af_vcp_system.fiber_surfaces[0]

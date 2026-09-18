"""Explicit debug presentation for delivered files, separate from ordinary editing."""
import bpy
from ...core.scp_runtime.object_colors import apply_object_color, ensure_scp_color, _set_area_object_color
from ...core.visualization.category_visibility import category_objects


def prepare_debug_presentation(root, scene):
    fibers = category_objects(scene, root, 'FIBER')
    supports = _support_objects(root, scene)
    objects = tuple(dict.fromkeys((*fibers, *supports)))
    _reveal(scene, objects)
    for obj in fibers:
        if obj.get('af_fiber_proxy'):
            obj.display_type = 'TEXTURED'; obj.hide_render = False
    _restore_support_colors(root, supports)
    _configure_views()
    return tuple(obj for obj in fibers if obj.get('af_fiber_proxy'))


def _support_objects(root, scene):
    ids = {scp.id for scp in root.af_scp_system.scps}
    return tuple(obj for obj in scene.objects if obj.get('af_root_name') == root.name
                 and obj.get('af_scp_geometry')
                 and (obj.get('af_source_scp_id') or obj.get('af_scp_id')) in ids)


def _restore_support_colors(root, objects):
    colors = {scp.id: ensure_scp_color(root, scp) for scp in root.af_scp_system.scps}
    for obj in objects:
        apply_object_color(obj, colors[obj.get('af_source_scp_id') or obj.get('af_scp_id')])
        obj.hide_render = False


def _reveal(scene, objects):
    targets = {collection for obj in objects for collection in obj.users_collection}
    for layer in scene.view_layers:
        _reveal_collections(layer.layer_collection, targets)
        layer.update()
        for obj in objects:
            obj.hide_viewport = False
            if layer.objects.get(obj.name) == obj:
                obj.hide_set(False, view_layer=layer)


def _reveal_collections(layer, targets):
    children = [_reveal_collections(child, targets) for child in layer.children]
    needed = layer.collection in targets or any(children)
    if needed:
        layer.exclude = False; layer.hide_viewport = False
        layer.collection.hide_viewport = False; layer.collection.hide_render = False
    return needed


def _configure_views():
    for screen in bpy.data.screens:
        for area in screen.areas:
            _set_area_object_color(area)
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.shading.type = 'SOLID'; space.shading.color_type = 'OBJECT'
                    space.show_object_viewport_curve = True
                    space.overlay.show_overlays = True

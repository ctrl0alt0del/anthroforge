import bpy

from ..id_utils import next_prefixed_id
from .bound_objects import ensure_bound_object, remove_bound_object, set_geometry_object, set_transform_object
from .common import scp_for_object
from .defaults import initialize_scp_entry


def active_scp_from_context(root, context):
    scp = scp_for_object(root, context.active_object) if context else None
    return scp or _active_scp_from_index(root)


def _active_scp_from_index(root):
    index = int(getattr(root.af_scp_system, "active_scp_index", -1))
    return root.af_scp_system.scps[index] if 0 <= index < len(root.af_scp_system.scps) else None


def create_empty_scp(root, context):
    scp = root.af_scp_system.scps.add()
    scp_id = next_prefixed_id(root.af_scp_system.scps, "SCP")
    initialize_scp_entry(scp, scp_id, scp_id)
    obj = bpy.data.objects.new(f"{scp_id}_XFORM", None)
    _target_collection(context).objects.link(obj)
    set_transform_object(root, scp, obj)
    return scp, obj


def _target_collection(context):
    scene = None if context is None else getattr(context, "scene", None)
    view_layer = None if context is None else getattr(context, "view_layer", None)
    layer = None if view_layer is None else getattr(view_layer, "active_layer_collection", None)
    if layer is not None:
        return layer.collection
    return scene.collection if scene is not None else bpy.context.scene.collection


def add_bound_object_to_scp(root, scp, obj):
    return ensure_bound_object(root, scp, obj) is not None


def set_scp_transform_object(root, scp, obj):
    return set_transform_object(root, scp, obj)


def set_scp_geometry_object(root, scp, obj):
    return set_geometry_object(root, scp, obj)


def remove_scp_bound_object(root, scp, bound_id):
    return remove_bound_object(root, scp, bound_id)

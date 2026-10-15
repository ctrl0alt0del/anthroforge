"""Position-only publication with compatibility and persistent identity checks."""
import json
import numpy as np
from .storage import load
from ...core.deformation.validation import validate_mesh_identity

IDENTITY_ATTRIBUTE = "af_deformation_vertex_id"


def compatible(obj):
    if obj is None or obj.type != "MESH": raise ValueError("Final skin mesh is unavailable.")
    if obj.data.shape_keys is not None:
        raise ValueError("Final skin has shape keys; updating its basis is not supported.")
    if any(modifier.type == "ARMATURE" for modifier in obj.modifiers) or obj.find_armature() is not None:
        raise ValueError("Final skin has an attached rig; deformation updates are not supported.")
    if obj.data.users > 1:
        raise ValueError("Final skin mesh is shared; make mesh data single-user before updating.")
    if obj.mode != "OBJECT": raise ValueError("Finish mesh editing before updating final skin.")


def mesh_identity(obj):
    mesh = obj.data
    if any(len(face.vertices) != 4 for face in mesh.polygons):
        raise ValueError("Final skin connectivity changed; reinitialize explicitly.")
    points = np.empty((len(mesh.vertices),3)); faces = np.empty((len(mesh.polygons),4),np.int32)
    mesh.vertices.foreach_get("co",points.ravel()); mesh.loops.foreach_get("vertex_index",faces.ravel())
    attribute = mesh.attributes.get(IDENTITY_ATTRIBUTE)
    if attribute is None or attribute.domain != "POINT" or attribute.data_type != "INT":
        raise ValueError("Final skin vertex identities are missing; initialize explicitly.")
    ids = np.empty(len(mesh.vertices),np.int32); attribute.data.foreach_get("value",ids)
    return points, faces, ids


def install_ids(obj, reference):
    compatible(obj)
    mesh = obj.data; attribute = mesh.attributes.get(IDENTITY_ATTRIBUTE)
    if attribute is None: attribute = mesh.attributes.new(IDENTITY_ATTRIBUTE,"INT","POINT")
    if attribute.domain != "POINT" or attribute.data_type != "INT":
        raise ValueError("Final skin identity attribute has an incompatible type.")
    if len(attribute.data) != len(reference.arrays["vertex_ids"]):
        raise ValueError("Cannot install identities on a different mesh.")
    attribute.data.foreach_set("value",reference.arrays["vertex_ids"])


def publish(root, obj, result, reference_signature):
    from ...core.mesh_issues import annotate
    compatible(obj); reference = load(root,obj)
    if reference.signature != reference_signature:
        raise ValueError("Stale deformation result: reference changed.")
    previous, faces, ids = mesh_identity(obj)
    validate_mesh_identity(reference,previous,faces,ids)
    validate_mesh_identity(reference,result.vertices,result.quads,ids)
    annotate(result,"topology_update")
    commit(root,obj,result,previous)
    return obj


def commit(root, obj, result, previous):
    statistics = json.dumps(result.statistics,sort_keys=True,allow_nan=False)
    old_properties = dict(obj.items()), dict(obj.data.items())
    try:
        obj.data.vertices.foreach_set("co",np.asarray(result.vertices).ravel()); obj.data.update()
        obj["af_topology_stats_json"] = statistics
        report_issues(root, obj, result)
    except Exception:
        obj.data.vertices.foreach_set("co",previous.ravel()); obj.data.update()
        restore_properties(obj,old_properties[0]); restore_properties(obj.data,old_properties[1])
        raise


def restore_properties(owner, properties):
    for key in tuple(owner.keys()):
        if key not in properties: del owner[key]
    for key, value in properties.items(): owner[key] = value


def report_issues(root, obj, result):
    from ..mesh_issues import persist, publish as publish_issues
    persist(obj,result,"topology_update")
    for scene in obj.users_scene:
        if root.name in scene.objects: publish_issues(obj,scene,root)

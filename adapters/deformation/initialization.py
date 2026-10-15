"""Explicit initialization captures on the main thread and retains construction outputs on failure."""
import json
from pathlib import Path
import numpy as np
from . import request, storage
from .capture import capture_anatomy
from .publication import compatible, install_ids


def capture(context, root, spec):
    from ..warm_update.current_output import current_topology_result, current_skin_result
    from ...core.topology.protocol import write_result
    from ..topology.capture import _resolved_plane, _root_settings
    obj = request.topology(root,context.scene); compatible(obj)
    result = current_topology_result(root,context.scene,obj); write_result(spec.current_topology_path,result)
    records, points, faces = capture_anatomy(root,context.scene,context.evaluated_depsgraph_get())
    arrays = {}; pack_sources(arrays,records,points,faces)
    skin = current_skin_result(root,context.scene)
    arrays.update(surface_vertices=result.vertices if skin is None else skin.vertices,
        surface_faces=np.concatenate((result.quads[:,[0,1,2]],result.quads[:,[0,2,3]])) if skin is None else skin.triangles)
    plane = _resolved_plane(root,_root_settings(root))
    arrays["plane"] = np.zeros(6) if plane is None else np.concatenate((plane.origin,plane.normal))
    np.savez(Path(spec.job_dir,"construction.npz"),**arrays)
    Path(spec.job_dir,"contributors.json").write_text(json.dumps(records),encoding="utf-8")


def pack_sources(arrays, records, points, faces):
    for index, row in enumerate(records):
        arrays[f"points_{index}"] = points[row["key"]]
        arrays[f"faces_{index}"] = faces[row["key"]]


def publish(scene, root, job):
    from ...core.deformation.serialization import decode
    from ...core.deformation.validation import validate_mesh_identity
    obj = request.topology(root,scene); compatible(obj)
    reference = decode(Path(job.spec.job_dir,"reference.txt").read_text(encoding="ascii"))
    points = np.empty((len(obj.data.vertices),3)); obj.data.vertices.foreach_get("co",points.ravel())
    faces = np.empty((len(obj.data.polygons),4),np.int32); obj.data.loops.foreach_get("vertex_index",faces.ravel())
    validate_mesh_identity(reference,points,faces,reference.arrays["vertex_ids"])
    if not np.allclose(points,reference.arrays["vertices"],rtol=0,atol=1e-7): raise ValueError("Topology changed during preparation.")
    install_ids(obj,reference); storage.store(root,obj,reference)
    remove_draft(scene,root,obj)
    return reference


def remove_draft(scene, root, obj):
    import bpy
    release_binding(obj)
    for attr in tuple(obj.data.attributes):
        if attr.name.startswith("af_topology_skin_"): obj.data.attributes.remove(attr)
    for item in tuple(scene.objects):
        if item.get("af_draft_skin") and item.get("af_root_name") == root.name:
            mesh = item.data; bpy.data.objects.remove(item,do_unlink=True)
            if not mesh.users: bpy.data.meshes.remove(mesh)


def release_binding(obj):
    import bpy
    previous = obj.get("af_bound_skin")
    if "af_bound_skin" in obj: del obj["af_bound_skin"]
    if previous is not None and not previous.users and previous.get("af_owned_binding_reference"):
        bpy.data.meshes.remove(previous)

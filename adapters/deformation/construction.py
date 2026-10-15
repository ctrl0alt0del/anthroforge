"""Publish construction and its reference together; preserve older final output on failure."""
from pathlib import Path
import bpy
from . import storage
from .publication import install_ids, compatible
from .initialization import remove_draft
from ...core.deformation.serialization import decode
from ..topology import output


def publish(scene, root, result, folder):
    path = Path(folder,"reference.txt"); previous = output._previous(scene,root)
    if not path.is_file():
        if root.get(storage.KEY) is not None:
            raise RuntimeError(result.statistics.get("deformation_preparation_error","Replacement reference unavailable; previous output retained."))
        return output.replace_topology(scene,root,result)
    reference = decode(path.read_text(encoding="ascii"))
    if previous is not None: compatible(previous)
    obj = transactional_mesh(scene,root,result,reference,previous)
    mark_ready(root,result)
    remove_draft(scene,root,obj)
    return obj


def mark_ready(root, result):
    from .request import construction_signature
    root["af_deformation_construction_signature"] = construction_signature(root)
    root["af_deformation_invalid"] = False
    root["af_deformation_construction_stale"] = False
    root["af_deformation_status"] = "Reference ready"
    root["af_deformation_issue_count"] = len(result.statistics.get("issues",()))


def transactional_mesh(scene, root, result, reference, previous):
    from .publication import restore_properties
    mesh = output._build_mesh(result); old_mesh = None if previous is None else previous.data; old = dict(root.items()), {} if previous is None else dict(previous.items())
    obj = previous or bpy.data.objects.new("AF_TOPOLOGY",mesh)
    try:
        if previous is None: output._output_collection(scene).objects.link(obj)
        obj.data = mesh; install_ids(obj,reference); storage.store(root,obj,reference)
        output._finish(scene,root,result,obj)
    except Exception:
        restore_properties(root,old[0])
        if previous is None: output._remove(obj)
        else: obj.data = old_mesh; restore_properties(obj,old[1]); bpy.data.meshes.remove(mesh)
        raise
    if old_mesh is not None and not old_mesh.users: bpy.data.meshes.remove(old_mesh)
    return obj

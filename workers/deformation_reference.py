"""One-time simulation proxy and immutable reference preparation."""
import json
from pathlib import Path
import bpy
import numpy as np
from core.deformation.construction import assemble
from core.deformation.contact import prepare_contact
from core.deformation.reference import DeformationSettings
from core.deformation.serialization import encode, decode
from core.deformation.proxy import tetrahedralize
from core.topology.protocol import read_result
from core.warm_start.job import read_job, write_status
from core.warm_start.model import WarmUpdateStatus


def run_reference_job(folder):
    spec = read_job(Path(folder)/"job.json"); result = read_result(spec.current_topology_path)
    records = json.loads(Path(folder,"contributors.json").read_text(encoding="utf-8"))
    write_status(spec.status_path,WarmUpdateStatus(True,"Preparing reference proxy",.1,state="RUNNING"))
    with np.load(Path(folder,"construction.npz"),allow_pickle=False) as source:
        reference = build(spec,result,records,source)
    payload = encode(reference)
    if decode(payload).signature != reference.signature: raise ValueError("Reference serialization failed.")
    Path(folder,"reference.txt").write_text(payload,encoding="ascii")
    if Path(spec.cancel_path).exists(): raise RuntimeError("CANCELLED")
    write_status(spec.status_path,WarmUpdateStatus(True,"Reference ready",1.,state="SUCCEEDED"))


def build(spec, result, records, source):
    points = {row["key"]:source[f"points_{i}"] for i,row in enumerate(records)}
    faces = {row["key"]:source[f"faces_{i}"] for i,row in enumerate(records)}
    vertices, triangles = decimate(source["surface_vertices"],source["surface_faces"])
    if Path(spec.cancel_path).exists(): raise RuntimeError("CANCELLED")
    settings = DeformationSettings(**spec.topology_update["settings"])
    proxy = tetrahedralize(vertices,triangles,settings.proxy_resolution)
    reference = assemble(result.vertices,result.quads,proxy,records,points,faces,settings,spec.cancel_path)
    plane = source["plane"]
    return prepare_contact(reference,plane[:3],plane[3:])


def decimate(vertices, triangles):
    mesh = bpy.data.meshes.new("deformation proxy"); mesh.from_pydata(vertices,[],triangles); mesh.update()
    obj = bpy.data.objects.new("deformation proxy",mesh); bpy.context.scene.collection.objects.link(obj)
    modifier = obj.modifiers.new("Proxy reduction","DECIMATE"); modifier.ratio = min(1.,64000/len(triangles))
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    try:
        output = evaluated.to_mesh(); output.calc_loop_triangles()
        points = np.empty((len(output.vertices),3)); faces = np.empty((len(output.loop_triangles),3),np.int32)
        output.vertices.foreach_get("co",points.ravel()); output.loop_triangles.foreach_get("vertices",faces.ravel())
        return points,faces
    finally:
        evaluated.to_mesh_clear(); bpy.data.objects.remove(obj,do_unlink=True); bpy.data.meshes.remove(mesh)

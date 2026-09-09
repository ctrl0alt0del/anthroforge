"""Main-thread RNA capture into immutable numerical records."""
import threading
import numpy as np
import bpy
from ...core.authoring.model import MeshSnapshot, SceneSnapshot, readonly
from ...core.authoring.codec import digest, decode
from ...core.authoring.errors import require
from ...core.scp_runtime.common import find_geometry_mesh_scp_obj
from .records import record


def snapshot(root, scene, scene_id):
    require(threading.current_thread() is threading.main_thread(), "MAIN_THREAD_REQUIRED")
    require(scene_id == root.name, "SCENE_NOT_FOUND", root.name)
    bpy.context.view_layer.update()
    meshes = tuple(capture_mesh(root, scene, s) for s in root.af_scp_system.scps)
    meshes = tuple(m for m in meshes if m is not None)
    payload = [(m.id, m.vertices.tolist(), m.triangles.tolist(), m.matrix.tolist(), m.concept, m.side, m.label) for m in meshes]
    payload.append(native_records(root))
    return SceneSnapshot(scene_id, digest(payload), meshes, str(root.get("af_authoring_pose", "rest")))


def capture_mesh(root, scene, scp):
    obj = find_geometry_mesh_scp_obj(scene, root.name, scp.id)
    if obj is None or obj.type != "MESH":
        return None
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        verts = readonly([tuple(v.co) for v in mesh.vertices])
        tris = readonly([tuple(t.vertices) for t in mesh.loop_triangles], int)
        require(len(verts) > 0 and len(tris) > 0, "EMPTY_COLLIDER", scp.id)
        return MeshSnapshot(scp.id, verts, tris, readonly(evaluated.matrix_world),
                            str(scp.get("af_anatomical_concept", "")), str(scp.get("af_anatomical_side", "midline")), scp.name)
    finally:
        evaluated.to_mesh_clear()


def native_records(root):
    vcp = root.af_vcp_system
    return {name: [record(item) for item in getattr(vcp, name)] for name in ("fibers", "fiber_surfaces", "muscles")}

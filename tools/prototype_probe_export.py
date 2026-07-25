import json
import sys

import bpy
import numpy as np


def output_path():
    args = sys.argv[sys.argv.index("--") + 1 :]
    return args[args.index("--output") + 1]


def is_source(obj):
    if obj.type != "MESH" or obj.get("af_draft_skin"):
        return False
    if obj.get("af_scp_geometry"):
        return True
    if obj.get("af_blob_proxy"):
        return True
    return obj.get("af_muscle_surface") == "INFL"


def source_kind(obj):
    return "SCP" if obj.get("af_scp_geometry") else "VCP"


def evaluated_arrays(obj, depsgraph):
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    mesh.calc_loop_triangles()
    matrix = evaluated.matrix_world
    vertices = np.array([tuple(matrix @ item.co) for item in mesh.vertices])
    faces = np.array([item.vertices[:] for item in mesh.loop_triangles], dtype=np.int32)
    evaluated.to_mesh_clear()
    return vertices, faces


def append_source(obj, depsgraph, vertices, faces, metadata):
    local_vertices, local_faces = evaluated_arrays(obj, depsgraph)
    if not len(local_vertices) or not len(local_faces):
        return
    faces.append(local_faces + sum(len(item) for item in vertices))
    vertices.append(local_vertices)
    metadata.append((obj.name, source_kind(obj), len(local_vertices)))


def capture_sources():
    depsgraph = bpy.context.evaluated_depsgraph_get()
    sources = [obj for obj in bpy.data.objects if is_source(obj)]
    vertices, faces, metadata = [], [], []
    for obj in sources:
        append_source(obj, depsgraph, vertices, faces, metadata)
    kinds = [np.full(count, kind) for _, kind, count in metadata]
    return np.concatenate(vertices), np.concatenate(faces), metadata, np.concatenate(kinds)


def save_capture(path):
    vertices, faces, metadata, kinds = capture_sources()
    bounds = [vertices.min(axis=0).tolist(), vertices.max(axis=0).tolist()]
    np.savez(path, vertices=vertices, faces=faces, metadata=json.dumps(metadata), vertex_kinds=kinds)
    print("AF_PROBE_CAPTURE", len(vertices), len(faces), bounds)


save_capture(output_path())

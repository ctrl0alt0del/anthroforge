import argparse
import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils.bvhtree import BVHTree


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--plane-origin", nargs=3, type=float)
    parser.add_argument("--plane-normal", nargs=3, type=float)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def mesh_arrays(obj):
    matrix = np.asarray(obj.matrix_world, dtype=np.float64)
    local = np.asarray([vertex.co[:] for vertex in obj.data.vertices], dtype=np.float64)
    homogeneous = np.column_stack((local, np.ones(len(local))))
    vertices = (homogeneous @ matrix.T)[:, :3]
    faces = tuple(tuple(polygon.vertices) for polygon in obj.data.polygons)
    return vertices, faces


def surface_tree(vertices, faces):
    return BVHTree.FromPolygons(vertices.tolist(), faces, all_triangles=False)


def distances(points, tree):
    values = [tree.find_nearest(point)[3] for point in points]
    return np.asarray(values, dtype=np.float64)


def distance_stats(points, tree):
    values = distances(points, tree)
    return {"mean": float(values.mean()), "p95": float(np.quantile(values, 0.95)),
            "maximum": float(values.max())}


def reflected(points, axis):
    values = points.copy()
    values[:, axis] *= -1.0
    return values


def plane_reflected(points, origin, normal):
    origin = np.asarray(origin, dtype=np.float64)
    normal = np.asarray(normal, dtype=np.float64)
    normal /= np.linalg.norm(normal)
    distances = (points - origin) @ normal
    return points - (2.0 * distances[:, None] * normal)


def symmetry_stats(vertices, tree):
    names = ("x", "y", "z")
    return {name: distance_stats(reflected(vertices, axis), tree)
            for axis, name in enumerate(names)}


def plane_symmetry_stats(vertices, tree, args):
    if args.plane_origin is None or args.plane_normal is None:
        return None
    return distance_stats(plane_reflected(
        vertices, args.plane_origin, args.plane_normal), tree)


def scene_meshes():
    objects = tuple(bpy.context.scene.objects)
    skin = next(obj for obj in objects if obj.get("af_draft_skin"))
    topology = next(obj for obj in objects if obj.name == "AF_INSTANT_STITCHED")
    return skin, topology


def payload(args):
    skin, topology = scene_meshes()
    skin_vertices, skin_faces = mesh_arrays(skin)
    topo_vertices, topo_faces = mesh_arrays(topology)
    skin_tree = surface_tree(skin_vertices, skin_faces)
    topo_tree = surface_tree(topo_vertices, topo_faces)
    scale = float(np.linalg.norm(skin_vertices.max(axis=0) - skin_vertices.min(axis=0)))
    return {"scale": scale, "skin_symmetry": symmetry_stats(skin_vertices, skin_tree),
            "plane_symmetry": plane_symmetry_stats(skin_vertices, skin_tree, args),
            "topology_to_skin": distance_stats(topo_vertices, skin_tree),
            "skin_to_topology": distance_stats(skin_vertices, topo_tree)}


def main():
    args = parse_args()
    values = payload(args)
    Path(args.output).write_text(json.dumps(values, indent=2), encoding="utf-8")
    print("AF_SURFACE_COMPARISON " + json.dumps(values), flush=True)


if __name__ == "__main__":
    main()

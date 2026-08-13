"""Read-only development probe for the conservative Fiber CCD reference."""

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import bpy
import numpy as np


def _args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--fiber", default="FIBER_14")
    parser.add_argument("--nodes", default="64,256,512")
    parser.add_argument("--clearance", type=float, default=0.002)
    parser.add_argument("--motion", type=float, default=0.002)
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--backend", choices=("reference", "native"), default="reference")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:])


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _register_addon():
    addons_dir = str(Path(__file__).resolve().parents[2])
    if addons_dir not in sys.path:
        sys.path.insert(0, addons_dir)
    import anthroforge
    anthroforge.register()


def _detach_handler():
    from anthroforge.core.visualization.fiber_sync import register_fiber_sync
    handler = register_fiber_sync().on_depsgraph_update
    if handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(handler)


def _load(path):
    _register_addon(); _detach_handler()
    bpy.ops.wm.open_mainfile(filepath=str(Path(path).resolve()), load_ui=False)
    _detach_handler()


def _root(scene):
    return next(obj for obj in scene.objects if obj.get("anthroforge_root"))


def _fiber(root, identifier):
    return next(item for item in root.af_vcp_system.fibers if item.id == identifier or item.name == identifier)


def _proxy(scene, root, identifier):
    return next(obj for obj in scene.objects if obj.get("af_fiber_proxy") and
                not obj.get("af_fiber_mirror_proxy") and obj.get("af_root_name") == root.name and
                str(obj.get("af_fiber_id")) == str(identifier))


def _spline_coordinates(spline):
    if spline.type == "BEZIER":
        return [point.co.copy() for point in spline.bezier_points]
    return [point.co.xyz.copy() for point in spline.points]


def _world_curve_points(proxy):
    local = [point for spline in proxy.data.splines for point in _spline_coordinates(spline)]
    return np.asarray([tuple(proxy.matrix_world @ point) for point in local], dtype=np.float64)


def _resample(points, count):
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(lengths)))
    if cumulative[-1] <= np.finfo(float).eps:
        return np.repeat(points[:1], count, axis=0)
    targets = np.linspace(0.0, cumulative[-1], count)
    indices = np.clip(np.searchsorted(cumulative, targets, side="right") - 1, 0, len(points) - 2)
    spans = cumulative[indices + 1] - cumulative[indices]
    fractions = np.divide(targets - cumulative[indices], spans, out=np.zeros(count), where=spans > 0.0)
    return points[indices] + fractions[:, None] * (points[indices + 1] - points[indices])


def _capture_surface(obj, depsgraph):
    from anthroforge.core.scp_runtime.surface import build_mesh_surface_data
    surface = build_mesh_surface_data(obj, depsgraph, cache={})
    vertices = np.asarray([tuple(value) for value in surface.get("verts_world", ())], dtype=np.float64)
    triangles = np.asarray(surface.get("triangles", ()), dtype=np.int64)
    return vertices, triangles


def _capture_colliders(scene, root, depsgraph):
    from anthroforge.core.scp_runtime.common import iter_geometry_mesh_scp_objects
    vertices, triangles, owners, offset = [], [], [], 0
    for obj in iter_geometry_mesh_scp_objects(scene, root.name):
        obj_vertices, obj_triangles = _capture_surface(obj, depsgraph)
        vertices.append(obj_vertices); triangles.append(obj_triangles + offset)
        owners.extend([str(obj.get("af_scp_id", ""))] * len(obj_triangles))
        offset += len(obj_vertices)
    return np.vstack(vertices), np.vstack(triangles), tuple(owners)


def _candidate_motion(points, amplitude):
    parameter = np.linspace(0.0, np.pi, len(points))
    displacement = np.zeros_like(points)
    displacement[:, 2] = float(amplitude) * np.sin(parameter)
    return points + displacement


def _owner_zones(points, root, scene, fiber, depsgraph, clearance):
    from mathutils import Vector
    from anthroforge.core.vcp.fiber_collision import CollisionOracle
    from anthroforge.core.vcp.fiber_solver import FiberSolver
    solver = FiberSolver(surface_offset=clearance)
    oracle = CollisionOracle(root, scene, depsgraph, clearance, clearance)
    params = solver._runtime_params(fiber, False)
    params["endpoint_owners"] = (str(fiber.a_parent_id), str(fiber.b_parent_id))
    nodes = [Vector(value) for value in points]
    return solver._owner_zone_limits(nodes, oracle, oracle.colliders(), params)


def _owner_filter(owners, zones):
    def allowed(edge_index, triangle_index):
        owner = owners[triangle_index]
        return not any(edge_index >= start - 1 and edge_index + 1 <= end + 1
                       for start, end in zones.get(owner, ()))
    return allowed


def _backend(name):
    if name == "native":
        from anthroforge.core.vcp.fiber_ccd_native import mesh_collision_free_step_native
        return mesh_collision_free_step_native
    from anthroforge.core.vcp.fiber_ccd_reference import mesh_collision_free_step_reference
    return mesh_collision_free_step_reference


def _run_once(points, vertices, triangles, owners, zones, clearance, motion, backend):
    edges = np.column_stack((np.arange(len(points) - 1), np.arange(1, len(points))))
    end = _candidate_motion(points, motion)
    pair_filter = _owner_filter(owners, zones)
    started = time.perf_counter()
    result = _backend(backend)(points, end, edges, vertices, triangles, clearance, pair_filter)
    elapsed = (time.perf_counter() - started) * 1000.0
    payload = dict(result.__dict__); payload["wall_ms"] = elapsed
    return payload


def _benchmark(args):
    original_hash = _file_hash(args.blend)
    _load(args.blend)
    scene, depsgraph = bpy.context.scene, bpy.context.evaluated_depsgraph_get()
    root = _root(scene); fiber = _fiber(root, args.fiber)
    source = _world_curve_points(_proxy(scene, root, fiber.id))
    vertices, triangles, owners = _capture_colliders(scene, root, depsgraph)
    rows = {}
    for count in (int(value) for value in args.nodes.split(",")):
        points = _resample(source, count)
        zones = _owner_zones(points, root, scene, fiber, depsgraph, args.clearance)
        rows[str(count)] = [_run_once(points, vertices, triangles, owners, zones, args.clearance, args.motion, args.backend)
                            for _index in range(max(1, args.repeat))]
    return _report(args, original_hash, rows, vertices, triangles, fiber)


def _report(args, original_hash, rows, vertices, triangles, fiber):
    return {"blend": str(Path(args.blend).resolve()), "hash_before": original_hash,
            "hash_after": _file_hash(args.blend), "fiber": fiber.id, "parents": [fiber.a_parent_id, fiber.b_parent_id],
            "clearance": args.clearance, "motion": args.motion, "vertices": len(vertices),
            "triangles": len(triangles), "runs": rows, "blender": bpy.app.version_string,
            "python": platform.python_version(), "platform": platform.platform(),
            "filter": "solver-derived local owner-contact zones", "backend": args.backend}


def main():
    result = _benchmark(_args())
    print("AF_CCD_PROBE_JSON=" + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

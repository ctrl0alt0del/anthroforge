import argparse
import json
import sys
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils.bvhtree import BVHTree


ADDON_ROOT = Path(__file__).resolve().parents[1]
for entry in (ADDON_ROOT.parent, ADDON_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--metrics", required=True)
    parser.add_argument("--render-dir")
    parser.add_argument("--factor", type=float, default=1.1)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def ensure_runtime():
    import anthroforge
    if not hasattr(bpy.types.Object, "af_scp_system"):
        anthroforge.register()
    from adapters.topology.vendor import ensure_worker_dependencies
    return ensure_worker_dependencies()


def scene_root():
    root = next((obj for obj in bpy.context.scene.objects if obj.get("anthroforge_root")), None)
    if root is None:
        raise RuntimeError("Warm-start experiment requires AF_ROOT.")
    return root


def output_object(flag):
    return next((obj for obj in bpy.context.scene.objects if obj.get(flag)), None)


def world_mesh(obj):
    mesh = obj.data
    vertices = np.asarray([obj.matrix_world @ vertex.co for vertex in mesh.vertices])
    mesh.calc_loop_triangles()
    faces = np.asarray([triangle.vertices[:] for triangle in mesh.loop_triangles], dtype=np.int32)
    return vertices, faces


def quad_mesh(obj):
    vertices = np.asarray([obj.matrix_world @ vertex.co for vertex in obj.data.vertices])
    faces = np.asarray([polygon.vertices[:] for polygon in obj.data.polygons], dtype=np.int32)
    return vertices, faces


def capture_sources(root):
    from adapters.draft_skin.capture import capture_skin
    depsgraph = bpy.context.evaluated_depsgraph_get()
    return capture_skin(root, bpy.context.scene, depsgraph)


def source_key(source):
    return source.entity_type, source.entity_id, source.mirror_role


def compatible_sources(before, after):
    current = {source_key(item): item for item in after.sources}
    pairs = [(item, current.get(source_key(item))) for item in before.sources]
    valid = [(old, new) for old, new in pairs if new is not None and len(old.vertices) == len(new.vertices)]
    warnings = [source_key(old) for old, new in pairs if new is None or len(old.vertices) != len(new.vertices)]
    return valid, warnings


def combined_source_motion(before, after):
    pairs, warnings = compatible_sources(before, after)
    old = np.concatenate([np.asarray(pair[0].vertices) for pair in pairs])
    new = np.concatenate([np.asarray(pair[1].vertices) for pair in pairs])
    return old, new, warnings


def deform_skin(vertices, source_old, source_new):
    from scipy.spatial import cKDTree
    started = time.perf_counter()
    distances, indices = cKDTree(source_old).query(vertices, k=4, workers=-1)
    weights = 1.0 / np.maximum(distances, 1.0e-6) ** 2
    weights /= weights.sum(axis=1, keepdims=True)
    motion = np.sum((source_new[indices] - source_old[indices]) * weights[:, :, None], axis=1)
    return vertices + motion, time.perf_counter() - started


def barycentric(point, triangle):
    first, second = triangle[1] - triangle[0], triangle[2] - triangle[0]
    relative = point - triangle[0]
    values = np.asarray(((first @ first, first @ second), (first @ second, second @ second)))
    solved = np.linalg.solve(values + (np.eye(2) * 1.0e-12), (relative @ first, relative @ second))
    return np.asarray((1.0 - solved.sum(), solved[0], solved[1]))


def bind_topology(points, skin_vertices, skin_faces):
    from mathutils import Vector
    started = time.perf_counter()
    tree = BVHTree.FromPolygons(skin_vertices.tolist(), skin_faces.tolist(), all_triangles=True)
    hits = [tree.find_nearest(Vector(point)) for point in points]
    triangles = np.asarray([hit[2] for hit in hits], dtype=np.int32)
    projected = np.asarray([hit[0] for hit in hits])
    bary = np.asarray([barycentric(point, skin_vertices[skin_faces[index]])
                       for point, index in zip(projected, triangles)])
    offsets = np.asarray([np.dot(point - hit[0], hit[1]) for point, hit in zip(points, hits)])
    return triangles, bary, offsets, time.perf_counter() - started


def face_normals(vertices, faces):
    points = vertices[faces]
    values = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    lengths = np.linalg.norm(values, axis=1); lengths[lengths < 1.0e-12] = 1.0
    return values / lengths[:, None]


def transfer_topology(binding, skin_vertices, skin_faces):
    triangles, bary, offsets, _elapsed = binding
    points = skin_vertices[skin_faces[triangles]]
    surface = np.sum(points * bary[:, :, None], axis=1)
    normals = face_normals(skin_vertices, skin_faces)[triangles]
    return surface + (offsets[:, None] * normals)


def apply_edit(factor):
    control = bpy.data.objects.get("frontal_lobe_hook")
    if control is None:
        raise RuntimeError("Cranium width shortcut control is missing.")
    control.scale.x *= factor
    from app.runtime_api import sync_context
    sync_context(bpy.context, bake=True, source="warm_start_test", event_type="BAKE")
    bpy.context.view_layer.update()


def solve_full_skin(capture):
    from core.draft_skin.solver import solve_capture
    started = time.perf_counter()
    result = solve_capture(capture, progress_update, lambda: False)
    return result, time.perf_counter() - started


def progress_update(stage, progress, message=""):
    print(f"AF_WARM_PROGRESS {progress:.3f} {stage}: {message}", flush=True)


def test_collection():
    collection = bpy.data.collections.get("AF_WARM_START_TEST")
    if collection is None:
        collection = bpy.data.collections.new("AF_WARM_START_TEST")
        bpy.context.scene.collection.children.link(collection)
    return collection


def mesh_object(name, vertices, faces):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(np.asarray(vertices).tolist(), [], np.asarray(faces).tolist())
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(name, mesh); test_collection().objects.link(obj)
    return obj


def solve_full_topology(root, skin, vendor):
    from adapters.topology.capture import capture_topology
    from adapters.topology.solver import solve_capture
    previous = output_object("af_draft_skin"); previous["af_draft_skin"] = False
    skin["af_draft_skin"], skin["af_root_name"] = True, root.name
    started = time.perf_counter()
    capture = capture_topology(root, bpy.context.scene, bpy.context.evaluated_depsgraph_get())
    result = solve_capture(capture, vendor, progress_update, lambda: False)
    skin["af_draft_skin"], previous["af_draft_skin"] = False, True
    return result, time.perf_counter() - started


def nearest_metrics(first, second):
    from scipy.spatial import cKDTree
    forward = cKDTree(second).query(first, workers=-1)[0]
    backward = cKDTree(first).query(second, workers=-1)[0]
    values = np.concatenate((forward, backward))
    return {"mean": float(values.mean()), "p95": float(np.quantile(values, .95)), "max": float(values.max())}


def directed_metrics(points, surface):
    from scipy.spatial import cKDTree
    values = cKDTree(surface).query(points, workers=-1)[0]
    return {"mean": float(values.mean()), "p95": float(np.quantile(values, .95)), "max": float(values.max())}


def edge_ratios(before, after, faces):
    edges = np.unique(np.sort(np.vstack([faces[:, (i, (i + 1) % 4)] for i in range(4)]), axis=1), axis=0)
    old = np.linalg.norm(before[edges[:, 0]] - before[edges[:, 1]], axis=1)
    new = np.linalg.norm(after[edges[:, 0]] - after[edges[:, 1]], axis=1)
    values = new / np.maximum(old, 1.0e-12)
    return {"p05": float(np.quantile(values, .05)), "median": float(np.median(values)), "p95": float(np.quantile(values, .95))}


def inversion_count(before, after, faces):
    first = np.cross(before[faces[:, 1]] - before[faces[:, 0]], before[faces[:, 2]] - before[faces[:, 0]])
    second = np.cross(after[faces[:, 1]] - after[faces[:, 0]], after[faces[:, 2]] - after[faces[:, 0]])
    return int(np.count_nonzero(np.sum(first * second, axis=1) < 0.0))


def material(name, color):
    value = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    value.diffuse_color = (*color, 1.0); value.use_nodes = False
    return value


def assign_material(obj, name, color):
    obj.data.materials.clear(); obj.data.materials.append(material(name, color))


def wire_copy(name, vertices, faces, color):
    obj = mesh_object(name, vertices, faces); assign_material(obj, name + "_MAT", color)
    modifier = obj.modifiers.new("AF_WIRE", "WIREFRAME"); modifier.thickness = 0.003
    return obj


def render_setup():
    from adapters.topology.engine import guides
    guides._render_settings(); guides._lights()
    return guides._camera()


def set_visible(visible):
    allowed = set(visible)
    for obj in bpy.context.scene.objects:
        if obj.type in {"MESH", "CURVE"}:
            obj.hide_render = obj not in allowed


def render_view(camera, visible, location, path):
    set_visible(visible); camera.location = location
    direction = np.asarray((0.0, 0.0, 1.05)) - np.asarray(location)
    camera.rotation_euler = direction_to_rotation(direction)
    bpy.context.scene.render.filepath = str(path); bpy.ops.render.render(write_still=True)


def direction_to_rotation(direction):
    from mathutils import Vector
    return Vector(direction).to_track_quat("-Z", "Y").to_euler()


def render_results(objects, folder):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    camera = render_setup(); views = {"front": (0.0, -8.0, 1.25), "threequarter": (4.6, -7.0, 2.8)}
    specs = (("baseline", (objects[0],)), ("warm_skin", (objects[1],)),
             ("full_skin", (objects[2],)), ("warm_topology", (objects[2], objects[3])),
             ("full_topology", (objects[2], objects[4])))
    for view, location in views.items():
        for name, visible in specs:
            render_view(camera, visible, location, folder / f"{name}_{view}.png")


def result_metrics(values):
    old_skin, warm_skin, full_skin, old_topology, warm_topology, full_topology = values[:6]
    skin_faces, topology_faces, timings, warnings = values[6:]
    diagonal = float(np.linalg.norm(np.ptp(full_skin, axis=0)))
    return {"edit": "Cranium Lobe Width", "factor": 1.1, "diagonal": diagonal,
            "skin_distance": nearest_metrics(warm_skin, full_skin),
            "topology_surface_distance": directed_metrics(warm_topology, full_skin),
            "topology_reference_distance": nearest_metrics(warm_topology, full_topology),
            "topology_edge_ratios": edge_ratios(old_topology, warm_topology, topology_faces),
            "skin_inversions": inversion_count(old_skin, warm_skin, skin_faces),
            "topology_inversions": inversion_count(old_topology, warm_topology, topology_faces),
            "timings": timings, "binding_warnings": warnings}


def baseline_state():
    root = scene_root()
    skin, topology = output_object("af_draft_skin"), output_object("af_topology")
    return root, skin, topology, capture_sources(root), world_mesh(skin), quad_mesh(topology)


def run_experiment(args, vendor):
    root, baseline_skin, _topology, old_capture, skin_data, topology_data = baseline_state()
    old_skin, skin_faces = skin_data; old_topology, topology_faces = topology_data
    apply_edit(args.factor); new_capture = capture_sources(root)
    source_old, source_new, warnings = combined_source_motion(old_capture, new_capture)
    warm_skin, skin_time = deform_skin(old_skin, source_old, source_new)
    binding = bind_topology(old_topology, old_skin, skin_faces)
    warm_topology = transfer_topology(binding, warm_skin, skin_faces)
    full_skin_result, full_skin_time = solve_full_skin(new_capture)
    full_skin = mesh_object("AF_FULL_REFERENCE_SKIN", full_skin_result.vertices, full_skin_result.triangles)
    full_topology_result, full_topology_time = solve_full_topology(root, full_skin, vendor)
    full_topology = np.asarray(full_topology_result.vertices); timings = timing_payload(skin_time, binding, full_skin_time, full_topology_time)
    values = (old_skin, warm_skin, full_skin_result.vertices, old_topology, warm_topology, full_topology,
              skin_faces, topology_faces, timings, warnings)
    return baseline_skin, create_visuals(values, full_skin, full_topology_result), result_metrics(values)


def timing_payload(skin_time, binding, full_skin_time, full_topology_time):
    return {"warm_skin_seconds": skin_time, "topology_bind_seconds": binding[3],
            "full_skin_seconds": full_skin_time, "full_topology_seconds": full_topology_time}


def create_visuals(values, full_skin, full_topology_result):
    old_skin, warm_skin, _full_values, _old_topology, warm_topology, _full_topology = values[:6]
    skin_faces, topology_faces = values[6:8]
    baseline = mesh_object("AF_BASELINE_SKIN_TEST", old_skin, skin_faces)
    warm = mesh_object("AF_WARM_SKIN_TEST", warm_skin, skin_faces)
    assign_material(baseline, "AF_BASELINE_MAT", (.68, .78, .86)); assign_material(warm, "AF_WARM_MAT", (.18, .78, 1.0))
    assign_material(full_skin, "AF_FULL_MAT", (.78, .82, .86))
    warm_wire = wire_copy("AF_WARM_TOPOLOGY_TEST", warm_topology, topology_faces, (1.0, .25, .08))
    full_wire = wire_copy("AF_FULL_TOPOLOGY_TEST", full_topology_result.vertices, full_topology_result.quads, (.15, 1.0, .35))
    return baseline, warm, full_skin, warm_wire, full_wire


def write_results(args, objects, metrics):
    path = Path(args.metrics); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    if args.render_dir:
        render_results(objects, args.render_dir)
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.output).resolve()), compress=False)


def main():
    args = arguments(); vendor = ensure_runtime()
    _baseline, objects, metrics = run_experiment(args, vendor)
    metrics["factor"] = args.factor
    write_results(args, objects, metrics)
    print("AF_WARM_RESULT " + json.dumps(metrics, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()

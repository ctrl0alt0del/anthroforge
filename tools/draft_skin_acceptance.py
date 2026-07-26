import argparse
import json
import sys
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector


ADDON_ROOT = Path(__file__).resolve().parents[1]
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from app.use_cases.draft_skin import complete_generation, poll_generation, start_generation
from adapters.draft_skin.vendor import ensure_worker_dependencies
from core.utils import get_af_root


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", required=True)
    parser.add_argument("--render-dir")
    parser.add_argument("--reference")
    parser.add_argument("--reference-object", default="AF_VARIABLE_COLLAGEN_EAR_NOSE")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def ensure_registered():
    if hasattr(bpy.types.Object, "af_scp_system"):
        return
    import anthroforge
    anthroforge.register()


def solve_scene():
    root = get_af_root(bpy.context.scene)
    if root is None:
        raise RuntimeError("The acceptance scene has no AF_ROOT.")
    started = time.perf_counter()
    action = start_generation(bpy.context)
    if not action.ok:
        raise RuntimeError(action.message)
    print(f"AF_SKIN_ASYNC_START {time.perf_counter() - started:.3f}", flush=True)
    status = _wait_for_job()
    action = complete_generation(bpy.context, status)
    if not action.ok:
        raise RuntimeError(action.message)
    return root, action.value


def _wait_for_job():
    previous = None
    while True:
        status = poll_generation(bpy.context)
        current = (status.stage, round(status.progress, 3), status.message)
        if current != previous:
            print("AF_SKIN", *current, flush=True)
            previous = current
        if status.state in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return status
        time.sleep(0.25)


def save_result(path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(target), copy=True)


def material(name, color):
    value = bpy.data.materials.new(name)
    value.diffuse_color = (*color, 1.0)
    value.use_nodes = True
    shader = value.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1.0)
    shader.inputs["Roughness"].default_value = 0.48
    return value


def assign_material(obj, value):
    obj.data.materials.clear()
    obj.data.materials.append(value)


def source_objects(root):
    roles = ("af_scp_geometry", "af_muscle_proxy", "af_blob_proxy", "af_fiber_proxy")
    return [
        obj for obj in bpy.context.scene.objects if obj.type in {"MESH", "CURVE"}
        and obj.get("af_root_name") == root.name and any(obj.get(role) for role in roles)
        and str(obj.get("af_muscle_surface") or "INFL") != "BASE"
    ]


def prepare_sources(root):
    bone = material("AF Bone", (0.66, 0.52, 0.28))
    muscle = material("AF Muscle", (0.52, 0.035, 0.02))
    blob = material("AF Blob", (0.8, 0.18, 0.03))
    for obj in bpy.context.scene.objects:
        obj.hide_render = obj.type in {"MESH", "CURVE"}
    sources = source_objects(root)
    for obj in sources:
        assign_material(obj, _source_material(obj, bone, muscle, blob))
    return sources


def _source_material(obj, bone, muscle, blob):
    if obj.get("af_blob_proxy"):
        return blob
    return muscle if obj.get("af_muscle_proxy") or obj.get("af_fiber_proxy") else bone


def look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def add_camera():
    data = bpy.data.cameras.new("AF_SKIN_CAMERA")
    camera = bpy.data.objects.new("AF_SKIN_CAMERA", data)
    bpy.context.scene.collection.objects.link(camera)
    data.type, data.ortho_scale = "ORTHO", 3.35
    bpy.context.scene.camera = camera
    return camera


def add_light(name, location, energy, size):
    data = bpy.data.lights.new(name, "AREA")
    data.energy, data.shape, data.size = energy, "DISK", size
    light = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(light)
    light.location = location
    look_at(light, (0.0, 0.0, 1.3))


def prepare_render(folder):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = True
    scene.view_settings.look = "AgX - Medium High Contrast"
    Path(folder).mkdir(parents=True, exist_ok=True)


def setup_lights():
    add_light("AF Key", (-4.0, -5.0, 6.0), 1100.0, 4.0)
    add_light("AF Fill", (4.0, -3.0, 3.5), 750.0, 3.0)
    add_light("AF Rim", (0.0, 4.0, 5.0), 1000.0, 3.0)


def render_acceptance(root, skin, folder):
    ensure_worker_dependencies()
    sources = prepare_sources(root)
    assign_material(skin, material("AF Draft Skin", (0.12, 0.48, 0.82)))
    prepare_render(folder)
    setup_lights()
    camera = add_camera()
    for name, location in _views().items():
        _render_set(camera, location, sources, skin, Path(folder), name)


def compare_reference(skin, path, object_name):
    ensure_worker_dependencies()
    from core.draft_skin.mesh import signed_volume
    reference = _load_reference(path, object_name)
    first, first_faces = _object_arrays(skin)
    second, second_faces = _object_arrays(reference)
    metrics = _distance_metrics(first, first_faces, second, second_faces)
    volumes = signed_volume(first, first_faces), signed_volume(second, second_faces)
    metrics["relative_volume"] = abs(volumes[0] - volumes[1]) / max(abs(volumes[1]), 1.0e-12)
    metrics["voxel_size"] = json.loads(skin["af_skin_stats_json"])["voxel_size"]
    _require_parity(metrics)
    return metrics


def _load_reference(path, object_name):
    with bpy.data.libraries.load(str(path), link=False) as (available, loaded):
        if object_name not in available.objects:
            raise RuntimeError(f"Reference object {object_name} was not found.")
        loaded.objects = [object_name]
    return loaded.objects[0]


def _object_arrays(obj):
    mesh = obj.data
    mesh.calc_loop_triangles()
    vertices = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    faces = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.vertices.foreach_get("co", vertices)
    mesh.loop_triangles.foreach_get("vertices", faces)
    world = np.asarray(obj.matrix_world, dtype=np.float64)
    homogeneous = np.column_stack((vertices.reshape(-1, 3), np.ones(len(mesh.vertices))))
    return (homogeneous @ world.T)[:, :3], faces.reshape(-1, 3)


def _distance_metrics(first, first_faces, second, second_faces):
    first_distance = _directed_distance(first, second, second_faces)
    second_distance = _directed_distance(second, first, first_faces)
    return {
        "symmetric_max": float(max(first_distance.max(), second_distance.max())),
        "symmetric_mean": float((first_distance.mean() + second_distance.mean()) * 0.5),
        "symmetric_p99": float(max(np.quantile(first_distance, 0.99), np.quantile(second_distance, 0.99))),
    }


def _directed_distance(points, target, faces):
    from mathutils.bvhtree import BVHTree
    tree = BVHTree.FromPolygons(target.tolist(), faces.tolist(), all_triangles=True)
    return np.fromiter((tree.find_nearest(Vector(point))[3] for point in points), dtype=np.float64)


def _require_parity(metrics):
    if metrics["relative_volume"] >= 0.01:
        raise RuntimeError(f"Reference volume differs by {metrics['relative_volume']:.2%}.")
    limit = 1.5 * metrics["voxel_size"]
    if metrics["symmetric_p99"] >= limit:
        raise RuntimeError(f"Reference P99 distance {metrics['symmetric_p99']:.6f} exceeds {limit:.6f}.")


def _views():
    return {
        "front": (0.0, -8.0, 1.31),
        "threequarter": (5.0, -7.0, 3.0),
        "side": (8.0, 0.0, 1.31),
    }


def _render_set(camera, location, sources, skin, folder, name):
    camera.location = location
    look_at(camera, (0.0, 0.0, 1.31))
    _set_visible(sources, skin, True, False)
    structure = _render(folder / f"structure_{name}.png")
    _set_visible(sources, skin, False, True)
    rendered_skin = _render(folder / f"skin_{name}.png")
    _blend(structure, rendered_skin, folder / f"overlay_{name}.png")


def _set_visible(sources, skin, show_sources, show_skin):
    for obj in sources:
        obj.hide_render = not show_sources
    skin.hide_render = not show_skin


def _render(path):
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    return path


def _blend(structure, skin, output):
    from PIL import Image
    first = Image.open(structure).convert("RGBA")
    second = Image.open(skin).convert("RGBA")
    Image.blend(first, second, 0.55).save(output)


def main():
    args = parse_args()
    ensure_registered()
    root, skin = solve_scene()
    save_result(args.save)
    if args.reference:
        metrics = compare_reference(skin, args.reference, args.reference_object)
        print(f"AF_SKIN_PARITY {json.dumps(metrics, sort_keys=True)}", flush=True)
    if args.render_dir:
        render_acceptance(root, skin, args.render_dir)
    print(f"AF_SKIN_ACCEPTED {len(skin.data.vertices)} {len(skin.data.polygons)}", flush=True)


if __name__ == "__main__":
    main()

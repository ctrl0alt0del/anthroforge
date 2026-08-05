import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

ADDON_ROOT = Path(__file__).resolve().parents[1]
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--target", type=int, default=8100)
    parser.add_argument("--symmetry", choices=("NONE", "X", "Y", "Z"), default="X")
    parser.add_argument("--render-existing", action="store_true")
    parser.add_argument("--inspect-existing", action="store_true")
    parser.add_argument("--cleanup-existing", action="store_true")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def register_addon():
    import anthroforge
    if not hasattr(bpy.types.Object, "af_topology_settings"):
        anthroforge.register()


def current_root():
    return next((obj for obj in bpy.context.scene.objects if obj.get("af_root")),
                bpy.context.scene.objects.get("AF_ROOT"))


def configured_capture(root, args):
    from adapters.topology.capture import capture_topology
    root.af_topology_settings.target_quad_count = args.target
    root.af_topology_settings.symmetry_mode = args.symmetry
    clear_density_rules(root)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    return capture_topology(root, bpy.context.scene, depsgraph)


def clear_density_rules(root):
    for scp in root.af_scp_system.scps:
        scp.topology_density_mode = "INHERIT"
        scp.topology_subtree_quads = 0


def strategy_capture(capture, strategy):
    from core.topology.protocol import capture_hash
    settings = replace(capture.settings, refinement_strategy=strategy)
    values = (capture.root_name, capture.vertices, capture.triangles, capture.guides,
              settings, capture.plane, capture.density_rules, capture.ownership_sources)
    digest = capture_hash(*values)
    return replace(capture, settings=settings, input_hash=digest)


def progress(label):
    def update(stage, value, message):
        print(f"[{label} {value:0.2f}] {stage}: {message}", flush=True)
    return update


def solve(capture, vendor, label):
    from adapters.topology.solver import solve_capture
    return solve_capture(capture, vendor, progress(label))


def experiment_results(capture):
    from adapters.topology.vendor import ensure_worker_dependencies
    vendor = ensure_worker_dependencies()
    uniform = solve(strategy_capture(capture, "NONE"), vendor, "uniform")
    muscle = solve(strategy_capture(capture, "MUSCLE_PROXIMITY"), vendor, "muscle")
    return uniform, muscle


def new_collection(name):
    value = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(value)
    return value


def mesh_object(name, result, collection):
    mesh = bpy.data.meshes.new(f"{name}_MESH")
    mesh.from_pydata(result.vertices.tolist(), [], result.quads.tolist())
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def material(name, color, emission=0.0):
    value = bpy.data.materials.new(name)
    value.diffuse_color = (*color, 1.0)
    value.use_nodes = True
    node = value.node_tree.nodes.get("Principled BSDF")
    node.inputs["Base Color"].default_value = (*color, 1.0)
    node.inputs["Roughness"].default_value = 0.62
    node.inputs["Emission Color"].default_value = (*color, 1.0)
    node.inputs["Emission Strength"].default_value = emission
    return value


def assign_material(obj, value):
    obj.data.materials.clear()
    obj.data.materials.append(value)
    return obj


def wire_object(source, name, collection, value, thickness):
    wire = source.copy(); wire.data = source.data.copy(); wire.name = name
    collection.objects.link(wire); assign_material(wire, value)
    modifier = wire.modifiers.new("AF_PROTOTYPE_WIRE", "WIREFRAME")
    modifier.thickness, modifier.offset, modifier.use_replace = thickness, 1.0, True
    return wire


def palette():
    colors = ((0.95, 0.04, 0.02), (1.0, 0.25, 0.02), (1.0, 0.65, 0.03),
              (0.4, 0.9, 0.12), (0.03, 0.75, 0.72), (0.03, 0.35, 1.0))
    return tuple(material(f"AF_DENSITY_{index}", color, 0.3)
                 for index, color in enumerate(colors))


def density_indices(capture, vertices, quads, count):
    from adapters.topology.refinement_runtime import muscle_points
    from core.topology.refinement import muscle_proximity_weights
    from scipy.spatial import cKDTree
    centers = np.mean(np.asarray(vertices)[np.asarray(quads)], axis=1)
    distances = cKDTree(muscle_points(capture)).query(centers, workers=-1)[0]
    diagonal = float(np.linalg.norm(capture.upper - capture.lower))
    weights = muscle_proximity_weights(distances, diagonal)
    return np.minimum(((1.0 - weights) * count).astype(np.int32), count - 1)


def density_object(source, result, collection, capture):
    obj = source.copy(); obj.data = source.data.copy(); obj.name = "AF_MUSCLE_DENSITY_FIELD"
    collection.objects.link(obj); materials = palette()
    obj.data.materials.clear()
    for value in materials:
        obj.data.materials.append(value)
    indices = density_indices(capture, result.vertices, result.quads, len(materials))
    for polygon, index in zip(obj.data.polygons, indices):
        polygon.material_index = int(index)
    return obj


def existing_visual_objects():
    names = {"uniform": "AF_UNIFORM_TOPOLOGY", "uniform_wire": "AF_UNIFORM_WIRE",
             "muscle": "AF_MUSCLE_TOPOLOGY", "muscle_wire": "AF_MUSCLE_WIRE",
             "density": "AF_MUSCLE_DENSITY_FIELD"}
    return {key: bpy.data.objects[value] for key, value in names.items()}


def repair_density_materials(obj, capture, topology):
    values = palette(); obj.data.materials.clear()
    for value in values:
        obj.data.materials.append(value)
    vertices = np.asarray([tuple(item.co) for item in topology.data.vertices])
    quads = np.asarray([tuple(item.vertices) for item in topology.data.polygons])
    for polygon, index in zip(obj.data.polygons, density_indices(capture, vertices, quads, len(values))):
        polygon.material_index = int(index)


def object_bounds(obj):
    values = np.asarray([tuple(vertex.co) for vertex in obj.data.vertices], dtype=np.float64)
    return type("Bounds", (), {"lower": values.min(axis=0), "upper": values.max(axis=0)})()


def visual_objects(capture, uniform, muscle):
    collection = new_collection("AF_MUSCLE_REFINEMENT_TEST")
    diagonal = float(np.linalg.norm(capture.upper - capture.lower))
    base = material("AF_TEST_SURFACE", (0.055, 0.075, 0.105))
    cyan = material("AF_UNIFORM_WIRE", (0.03, 0.85, 1.0), 1.5)
    orange = material("AF_MUSCLE_WIRE", (1.0, 0.28, 0.025), 1.5)
    objects = _topology_objects(uniform, muscle, collection, base, cyan, orange, diagonal)
    objects["density"] = density_object(objects["muscle"], muscle, collection, capture)
    return objects


def _topology_objects(uniform, muscle, collection, base, cyan, orange, diagonal):
    first = assign_material(mesh_object("AF_UNIFORM_TOPOLOGY", uniform, collection), base)
    second = assign_material(mesh_object("AF_MUSCLE_TOPOLOGY", muscle, collection), base)
    thickness = 0.00055 * diagonal
    return {"uniform": first, "uniform_wire": wire_object(first, "AF_UNIFORM_WIRE", collection, cyan, thickness),
            "muscle": second, "muscle_wire": wire_object(second, "AF_MUSCLE_WIRE", collection, orange, thickness)}


def face_areas(vertices, faces):
    points = np.asarray(vertices)[np.asarray(faces)]
    first = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    second = np.cross(points[:, 2] - points[:, 0], points[:, 3] - points[:, 0])
    return 0.5 * (np.linalg.norm(first, axis=1) + np.linalg.norm(second, axis=1))


def proximity_metrics(capture, result):
    from adapters.topology.refinement_runtime import muscle_points
    from scipy.spatial import cKDTree
    centers = np.mean(np.asarray(result.vertices)[np.asarray(result.quads)], axis=1)
    points, diagonal = muscle_points(capture), float(np.linalg.norm(capture.upper - capture.lower))
    mask = cKDTree(points).query(centers, workers=-1)[0] <= 0.05 * diagonal
    areas = face_areas(result.vertices, result.quads)
    return _proximity_payload(mask, areas)


def _proximity_payload(mask, areas):
    inside, outside = areas[mask], areas[~mask]
    near = float(np.median(inside)) if len(inside) else 0.0
    far = float(np.median(outside)) if len(outside) else 0.0
    return {"faces": int(len(areas)), "muscle_near_faces": int(np.count_nonzero(mask)),
            "muscle_near_fraction": float(np.mean(mask)), "near_median_area": near,
            "far_median_area": far, "far_to_near_area_ratio": far / max(near, 1.0e-12)}


def metrics(capture, uniform, muscle):
    return {"target_quads": capture.settings.target_quad_count,
            "uniform": proximity_metrics(capture, uniform),
            "muscle_proximity": proximity_metrics(capture, muscle),
            "uniform_validation": uniform.statistics,
            "muscle_validation": muscle.statistics}


def configure_render(center, diagonal):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = scene.render.resolution_y = 760
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.world.color = (0.004, 0.006, 0.012)
    scene.view_settings.look = "AgX - Medium High Contrast"
    add_lights(center, diagonal)


def add_lights(center, diagonal):
    add_light("AF_TEST_KEY", center, (-diagonal, -diagonal, diagonal), 1600.0, diagonal)
    add_light("AF_TEST_FILL", center, (diagonal, -0.4 * diagonal, 0.2 * diagonal), 900.0, diagonal)


def add_light(name, center, offset, energy, size):
    data = bpy.data.lights.new(name, "AREA")
    data.energy, data.shape, data.size = energy, "DISK", size
    obj = bpy.data.objects.new(name, data); obj.location = Vector(center) + Vector(offset)
    bpy.context.scene.collection.objects.link(obj); point_at(obj, center)


def camera(center, height):
    data = bpy.data.cameras.new("AF_TEST_CAMERA")
    data.type, data.ortho_scale = "ORTHO", 1.08 * height
    obj = bpy.data.objects.new("AF_TEST_CAMERA", data)
    bpy.context.scene.collection.objects.link(obj); bpy.context.scene.camera = obj
    point_at(obj, center)
    return obj


def point_at(obj, center):
    obj.rotation_euler = (Vector(center) - obj.location).to_track_quat("-Z", "Y").to_euler()


def set_visible(objects):
    visible = set(objects)
    for obj in bpy.context.scene.objects:
        obj.hide_render = obj not in visible and obj.type not in {"CAMERA", "LIGHT"}


def render_view(camera_obj, center, diagonal, direction, objects, path):
    camera_obj.location = Vector(center) + Vector(direction).normalized() * 1.8 * diagonal
    point_at(camera_obj, center); set_visible(objects)
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def render_all(capture, objects, folder):
    folder.mkdir(parents=True, exist_ok=True)
    center = 0.5 * (capture.lower + capture.upper)
    diagonal = float(np.linalg.norm(capture.upper - capture.lower))
    configure_render(center, diagonal); camera_obj = camera(center, capture.upper[2] - capture.lower[2])
    groups = _render_groups(objects)
    for name, direction, visible in groups:
        render_view(camera_obj, center, diagonal, direction, visible, folder / f"{name}.png")
    contact_sheet(folder, groups)


def _render_groups(objects):
    front, quarter = (0.0, -1.0, 0.0), (0.7, -1.0, 0.18)
    uniform = (objects["uniform"], objects["uniform_wire"])
    muscle = (objects["muscle"], objects["muscle_wire"])
    return (("uniform_front", front, uniform), ("muscle_front", front, muscle),
            ("density_front", front, (objects["density"],)),
            ("uniform_threequarter", quarter, uniform),
            ("muscle_threequarter", quarter, muscle),
            ("density_threequarter", quarter, (objects["density"],)))


def contact_sheet(folder, groups):
    from PIL import Image, ImageDraw
    images = [Image.open(folder / f"{name}.png").convert("RGB") for name, _direction, _visible in groups]
    canvas = Image.new("RGB", (2280, 1520), (4, 6, 12))
    labels = ("Uniform topology", "Muscle-proximity topology", "Density field: red = dense",
              "Uniform topology", "Muscle-proximity topology", "Density field: red = dense")
    for index, (image, label) in enumerate(zip(images, labels)):
        paste_panel(canvas, image, label, index)
    canvas.save(folder / "muscle_density_comparison.png")


def paste_panel(canvas, image, label, index):
    from PIL import ImageDraw
    x, y = (index % 3) * 760, (index // 3) * 760
    canvas.paste(image, (x, y)); draw = ImageDraw.Draw(canvas)
    draw.rectangle((x, y, x + 350, y + 36), fill=(4, 6, 12))
    draw.text((x + 12, y + 9), label, fill=(238, 242, 250))


def save_outputs(args, values):
    folder = Path(args.render_dir); folder.mkdir(parents=True, exist_ok=True)
    (folder / "metrics.json").write_text(json.dumps(values, indent=2), encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.output).resolve()))


def prepare_viewport(objects):
    for name, obj in objects.items():
        obj.hide_set(name != "muscle")
        obj.hide_viewport = name != "muscle"
    objects["muscle"].show_wire = True
    objects["muscle"].show_all_edges = True


def cleanup_existing(args):
    prepare_viewport(existing_visual_objects())
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.output).resolve()))


def render_existing(args):
    from adapters.topology.vendor import ensure_worker_dependencies
    ensure_worker_dependencies()
    capture = configured_capture(current_root(), args)
    objects = existing_visual_objects()
    repair_density_materials(objects["density"], capture, objects["muscle"])
    render_all(capture, objects, Path(args.render_dir))
    prepare_viewport(objects)
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.output).resolve()))


def inspect_existing():
    for name, obj in existing_visual_objects().items():
        print("AF_INSPECT", name, mesh_diagnostics(obj), flush=True)


def mesh_diagnostics(obj):
    from collections import Counter
    faces = [tuple(polygon.vertices) for polygon in obj.data.polygons]
    edges = Counter(tuple(sorted((face[i], face[(i + 1) % 4])))
                    for face in faces for i in range(4))
    return {"vertices": len(obj.data.vertices), "faces": len(faces),
            "boundary_edges": sum(value == 1 for value in edges.values()),
            "overused_edges": sum(value > 2 for value in edges.values()),
            "duplicate_faces": len(faces) - len({tuple(sorted(face)) for face in faces}),
            "viewport_hidden": bool(obj.hide_viewport or obj.hide_get())}


def main():
    args = arguments(); register_addon(); root = current_root()
    if dispatch_existing(args):
        return
    if root is None:
        raise RuntimeError("Prototype scene has no AF_ROOT.")
    capture = configured_capture(root, args)
    uniform, muscle = experiment_results(capture)
    objects = visual_objects(capture, uniform, muscle)
    values = metrics(capture, uniform, muscle)
    render_all(capture, objects, Path(args.render_dir))
    prepare_viewport(objects)
    save_outputs(args, values)


def dispatch_existing(args):
    if args.inspect_existing:
        inspect_existing(); return True
    if args.cleanup_existing:
        cleanup_existing(args); return True
    if args.render_existing:
        render_existing(args); return True
    return False


if __name__ == "__main__":
    main()

"""Create a temporary real-scene .blend for repaired-pin route inspection."""

import argparse
import json
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_package42_maxilla_benchmark as base


def _arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--value", type=float, default=.2)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _collection():
    old = bpy.data.collections.get("AF_PACKAGE42_REVIEW")
    if old:
        bpy.data.collections.remove(old)
    value = bpy.data.collections.new("AF_PACKAGE42_REVIEW")
    bpy.context.scene.collection.children.link(value); return value


def _material(name, color):
    value = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    value.diffuse_color = (*color, 1.0); value.use_nodes = True
    shader = value.node_tree.nodes.get("Principled BSDF"); shader.inputs["Base Color"].default_value = (*color, 1.0)
    shader.inputs["Roughness"].default_value = .48; return value


def _curve(collection, name, points, radius, material, role):
    data = bpy.data.curves.new(name, "CURVE"); data.dimensions = "3D"
    data.bevel_depth = radius; data.bevel_resolution = 3
    spline = data.splines.new("POLY"); spline.points.add(len(points) - 1)
    for row, point in zip(spline.points, points):
        row.co = (*point, 1.0)
    data.materials.append(material); obj = bpy.data.objects.new(name, data); collection.objects.link(obj)
    obj["af_review_role"] = role; return obj


def _marker(collection, name, point, radius, material, role):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=radius, location=point)
    obj = bpy.context.object
    for group in tuple(obj.users_collection):
        group.objects.unlink(obj)
    collection.objects.link(obj); obj.name = name; obj.data.materials.append(material)
    obj["af_review_role"] = role; return obj


def _route_objects(collection, record, materials):
    original, p41, p42 = materials
    _curve(collection, "01_ORIGINAL_V1_ROLLED_BACK", record["v1_after"], .0014, original, "original_v1")
    left = _curve(collection, "02_REPAIRED_PACKAGE_4_1", record["repaired"]["package41"]["reference"], .0011, p41, "package41")
    right = _curve(collection, "03_REPAIRED_PACKAGE_4_2_IDENTICAL", record["repaired"]["package42"]["reference"], .0018, p42, "package42")
    right.hide_viewport = True; right.hide_render = True; left["validated"] = True; right["validated"] = True


def _pin_objects(collection, record, materials):
    old, fixed, anchor = materials
    for index, point in enumerate(record["anchors_fixed"]):
        _marker(collection, f"ANCHOR_{index}", point, .003, anchor, "hard_anchor")
    for index, (before, after) in enumerate(zip(record["original_pins"], record["fixed_pins"]), start=4):
        _marker(collection, f"PIN_{index}_OLD_INVALID", before, .0045, old, "old_invalid_pin")
        _marker(collection, f"PIN_{index}_REPAIRED", after, .004, fixed, "repaired_pin")
        _curve(collection, f"PIN_{index}_DISPLACEMENT", (before, after), .0006, old, "pin_displacement")


def _readme(record):
    text = bpy.data.texts.get("PACKAGE42_REVIEW_README") or bpy.data.texts.new("PACKAGE42_REVIEW_README")
    text.clear(); text.write("Package 4.2 repaired-pin review\n\n")
    text.write("Maxilla Top Radius = 0.2. Source file was not overwritten.\n")
    text.write("Red/orange: stored V1 rollback. Blue: Package 4.1. Green: Package 4.2 (hidden; identical).\n")
    text.write("Red spheres: invalid original pins. Yellow spheres: repaired pins. Cyan: all repaired anchors.\n")
    text.write(f"Pin displacements: {record['pin_displacements']} world units.\n")
    text.write("The repaired points are sampled SCP_10 surface positions for visual experimentation, not authored anatomy.\n")


def _apply_scene_edit(value):
    root = base.bench._root(); base._shortcut(root).proxy_float = value
    base._settle(); bpy.context.view_layer.update()


def _build(record):
    collection = _collection(); original = _material("AF_REVIEW_V1", (1.0, .12, .02))
    p41 = _material("AF_REVIEW_P41", (.02, .35, 1.0)); p42 = _material("AF_REVIEW_P42", (.02, 1.0, .18))
    old = _material("AF_REVIEW_INVALID_PIN", (1.0, .01, .01)); fixed = _material("AF_REVIEW_REPAIRED_PIN", (1.0, .75, .01))
    anchor = _material("AF_REVIEW_ANCHOR", (.01, .85, 1.0)); _route_objects(collection, record, (original, p41, p42))
    _pin_objects(collection, record, (old, fixed, anchor)); _readme(record)


def _select_review():
    bpy.ops.object.select_all(action="DESELECT")
    obj = bpy.data.objects.get("02_REPAIRED_PACKAGE_4_1")
    obj.select_set(True); bpy.context.view_layer.objects.active = obj


def main():
    args = _arguments(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    _apply_scene_edit(args.value); _build(record); _select_review()
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False, copy=True)
    print("AF_PACKAGE42_REVIEW", output, flush=True)


if __name__ == "__main__":
    main()

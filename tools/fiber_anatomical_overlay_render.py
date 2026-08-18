"""Render Fiber comparisons against real world-space SCP collider surfaces."""

import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector
import numpy as np

from anthroforge.tools import fiber_v24_benchmark as capture
from anthroforge.tools import fiber_v2_planner_benchmark as common
from anthroforge.core.vcp.v2 import cached_native_collision_world_batch


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True); parser.add_argument("--blend-output", default="")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _ensure_addon():
    if hasattr(bpy.types.Object, "af_vcp_system"): return
    import anthroforge
    anthroforge.register()


def _paths(record):
    visual = record["visual"]
    return {key: np.asarray(visual[key], dtype=np.float64) for key in ("source", "planner", "v24", "v25")}


def _capture():
    root = common._root(); scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    colliders, _elapsed = capture._native_colliders(scene, root, depsgraph)
    return colliders


def _focus(paths, radius):
    cloud = np.vstack(tuple(paths.values())); low, high = cloud.min(axis=0), cloud.max(axis=0)
    margin = max(float(np.linalg.norm(high - low)) * .16, radius * 8.0)
    return low - margin, high + margin


def _crop(collider, low, high):
    vertices = np.asarray(collider.vertices); faces = np.asarray(collider.triangles)
    triangles = vertices[faces]; inside = np.logical_and(triangles <= high, triangles >= low).all(axis=2)
    keep = np.any(inside, axis=1)
    return triangles[keep]


def _reset():
    bpy.ops.object.select_all(action="SELECT"); bpy.ops.object.delete(use_global=False)
    groups = (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.cameras, bpy.data.lights)
    for group in groups:
        for item in list(group): group.remove(item)


def _shader(name, color, alpha=1.0, emission=0.0):
    material = bpy.data.materials.new(name); material.diffuse_color = (*color, alpha); material.use_nodes = True
    node = material.node_tree.nodes.get("Principled BSDF"); node.inputs["Base Color"].default_value = (*color, 1.0)
    node.inputs["Roughness"].default_value = .68; node.inputs["Alpha"].default_value = alpha
    _emission(node, color, emission); _transparency(material, alpha); return material


def _emission(node, color, strength):
    if "Emission Color" not in node.inputs: return
    node.inputs["Emission Color"].default_value = (*color, 1.0)
    node.inputs["Emission Strength"].default_value = strength


def _transparency(material, alpha):
    if alpha >= 1.0 or not hasattr(material, "surface_render_method"): return
    material.surface_render_method = "DITHERED"


def _materials(owners):
    colors = ((.86, .22, .18), (.10, .48, .92), (1.0, .58, .10), (.43, .74, .25))
    owner = {value: _shader(f"OWNER_{value}", colors[index % len(colors)], .42) for index, value in enumerate(owners)}
    curves = {"source": _shader("STORED_V1", (1.0, .38, .04), 1.0, .35),
              "planner": _shader("PLANNER", (.02, .88, 1.0), 1.0, .35),
              "v24": _shader("V2_4", (.91, .12, 1.0), 1.0, .35),
              "v25": _shader("GUARDED", (.08, 1.0, .26), 1.0, .35)}
    return _shader("UNRELATED", (.34, .38, .43), .16), owner, curves, _shader("PINS", (1.0, .94, .05), 1.0, .3)


def _mesh(name, triangles, material):
    if not len(triangles): return
    vertices = triangles.reshape((-1, 3)); faces = np.arange(len(vertices)).reshape((-1, 3))
    data = bpy.data.meshes.new(name); data.from_pydata(vertices.tolist(), [], faces.tolist()); data.materials.append(material)
    obj = bpy.data.objects.new(name, data); bpy.context.collection.objects.link(obj)


def _curve(name, points, radius, material):
    data = bpy.data.curves.new(name, "CURVE"); data.dimensions = "3D"; data.bevel_depth = radius; data.bevel_resolution = 3
    spline = data.splines.new("POLY"); spline.points.add(len(points) - 1)
    for point, value in zip(spline.points, points): point.co = (*value, 1.0)
    data.materials.append(material); obj = bpy.data.objects.new(name, data); bpy.context.collection.objects.link(obj)
    return obj


def _pins(points, radius, material):
    for index, point in enumerate(points):
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=radius, location=point)
        bpy.context.object.name = f"PIN_{index}"; bpy.context.object.data.materials.append(material)


def _camera(name, center, direction, scale):
    data = bpy.data.cameras.new(name); data.type = "ORTHO"; data.ortho_scale = scale
    data.clip_start = max(scale * 1.0e-4, 1.0e-6); data.clip_end = max(scale * 10.0, 10.0)
    obj = bpy.data.objects.new(name, data); bpy.context.collection.objects.link(obj)
    obj.location = Vector(center) + Vector(direction) * scale * 1.8
    obj.rotation_euler = (Vector(center) - obj.location).to_track_quat("-Z", "Y").to_euler()
    return obj


def _light(name, center, direction, scale, energy):
    data = bpy.data.lights.new(name, "AREA"); data.energy = energy; data.size = scale * 1.3
    obj = bpy.data.objects.new(name, data); bpy.context.collection.objects.link(obj)
    obj.location = Vector(center) + Vector(direction) * scale
    obj.rotation_euler = (Vector(center) - obj.location).to_track_quat("-Z", "Y").to_euler()


def _scene(output):
    scene = bpy.context.scene; scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1400; scene.render.resolution_y = 1050; scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"; scene.render.filepath = str(output)
    scene.world.color = (.012, .016, .023); scene.view_settings.look = "AgX - Medium High Contrast"


def _visibility(curves, visible):
    for key, obj in curves.items(): obj.hide_render = key not in visible


def _render_views(output_dir, cameras, closeups, curves, diagnostics):
    variants = {"stored_vs_guarded": ("source", "v25"), "planner_vs_v24": ("planner", "v24"),
                "planner_vs_guarded": ("planner", "v25"),
                "v24_vs_guarded": ("v24", "v25")}
    for variant, visible in variants.items():
        _visibility(curves, visible)
        for view, camera in cameras.items():
            output = output_dir / f"{variant}_{view}.png"; _scene(output)
            bpy.context.scene.camera = camera; bpy.ops.render.render(write_still=True)
    _render_diagnostics(output_dir, cameras, closeups, curves, diagnostics)


def _render_diagnostics(output_dir, cameras, closeups, curves, diagnostics):
    _visibility(curves, ()); _diagnostic_visibility(diagnostics, True)
    for view, camera in cameras.items():
        output = output_dir / f"clearance_diagnostic_{view}.png"; _scene(output)
        bpy.context.scene.camera = camera; bpy.ops.render.render(write_still=True)
    _render_closeups(output_dir, closeups)
    _diagnostic_visibility(diagnostics, False)


def _render_closeups(output_dir, cameras):
    for view, camera in cameras.items():
        output = output_dir / f"clearance_close_{view}.png"; _scene(output)
        bpy.context.scene.camera = camera; bpy.ops.render.render(write_still=True)


def _diagnostic_visibility(objects, visible):
    for obj in objects: obj.hide_render = not visible


def _build_surfaces(colliders, bounds, owners, materials):
    neutral, owner_materials = materials[0], materials[1]
    for index, collider in enumerate(colliders):
        triangles = _crop(collider, *bounds); material = owner_materials.get(collider.owner_id, neutral)
        _mesh(f"{collider.owner_id or 'COLLIDER'}_{index}", triangles, material)


def _build_curves(paths, radius, materials):
    widths = {"source": .88, "planner": 1.7, "v24": .82, "v25": 1.28}; result = {}
    for key in ("source", "planner", "v24", "v25"):
        _curve(key, paths[key], radius * widths[key], materials[2][key]); result[key] = bpy.context.collection.objects[key]
    return result


def _diagnostic_materials():
    return {"core": _shader("CLEARANCE_CORE", (.08, 1.0, .26), 1.0, .5),
            "shell": _shader("CLEARANCE_SHELL", (.08, .55, 1.0), .22, .1),
            "safe": _shader("GAP_SAFE", (.1, 1.0, .2), 1.0, .4),
            "near": _shader("GAP_NEAR", (1.0, .65, .02), 1.0, .5),
            "inside": _shader("GAP_INSIDE", (1.0, .02, .02), 1.0, .6)}


def _diagnostic_rows(points, colliders):
    world = cached_native_collision_world_batch(colliders)
    closest, normals, distances, blockers, contained = world.nearest(points)
    return closest, normals, distances, blockers, contained


def _diagnostic_objects(points, radius, rows):
    mats = _diagnostic_materials()
    objects = [_curve("CLEARANCE_RADIUS", points, radius, mats["shell"]),
               _curve("CLEARANCE_CENTERLINE", points, radius * .24, mats["core"])]
    for index in range(0, len(points), 4): objects.extend(_gap_objects(index, points, rows, radius, mats))
    return objects, _diagnostic_normal(rows)


def _gap_objects(index, points, rows, radius, materials):
    closest, _normals, distances, _blockers, contained = rows
    key = _gap_key(float(distances[index]), bool(contained[index]), radius); material = materials[key]
    line = _curve(f"GAP_{index:03d}_{key}", (points[index], closest[index]), radius * .14, material)
    return (line, _marker(f"SURFACE_{index:03d}_{key}", closest[index], radius * .42, material))


def _gap_key(distance, contained, radius):
    if contained: return "inside"
    return "near" if distance < radius else "safe"


def _marker(name, point, radius, material):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=radius, location=point)
    obj = bpy.context.object; obj.name = name; obj.data.materials.append(material); return obj


def _diagnostic_normal(rows):
    normals = np.asarray(rows[1]); contained = np.asarray(rows[4], dtype=bool)
    weights = np.where(contained, 2.0, 1.0)[:, None]; value = np.sum(normals * weights, axis=0)
    length = float(np.linalg.norm(value)); return value / length if length > 1.0e-12 else np.array((1.0, 0.0, 0.0))


def _closeup_cameras(points, rows, radius, pins):
    closest, normals = rows[:2]; indices = _closeup_indices(len(points), pins); result = {}
    for index in indices:
        center = (points[index] + closest[index]) * .5; scale = max(radius * 18.0, .02)
        direction = _profile_direction(points, normals, index)
        result[f"node_{index:02d}"] = _camera(f"CLOSE_{index:02d}", center, direction, scale)
    return result


def _profile_direction(points, normals, index):
    low, high = max(0, index - 1), min(len(points) - 1, index + 1)
    tangent = points[high] - points[low]; direction = np.cross(tangent, normals[index])
    length = float(np.linalg.norm(direction)); return direction / length if length > 1.0e-12 else (1.0, 0.0, 0.0)


def _closeup_indices(count, pins):
    candidates = np.linspace(2, count - 3, 5, dtype=int); blocked = set(int(value) for value in pins)
    return tuple(int(value) for value in candidates if int(value) not in blocked)


def _arc_parameters(points):
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1); values = np.r_[0.0, np.cumsum(lengths)]
    return values / values[-1] if values[-1] > 0.0 else values


def _clearance_curve(points, rows, colliders, radius, contacts):
    closest, _normals, distances, blockers, contained = rows; owners = _collider_owners(colliders)
    legal = _legal_nodes(contacts); signed = np.where(contained, -distances, distances)
    return {"arc": _arc_parameters(points).tolist(), "ratio": (signed / radius).tolist(),
            "distance": signed.tolist(), "blockers": list(blockers),
            "blocker_owners": [owners.get(value, "") for value in blockers], "legal_contact": legal}


def _collider_owners(colliders):
    return {item.collider_id: item.owner_id for item in colliders}


def _legal_nodes(contacts):
    values = set()
    for row in contacts:
        values.update(int(index) for index in row.get("node_indices", ()))
    return sorted(values)


def _diagnostic_payload(paths, colliders, radius, corrected_rows, record):
    contacts = record["request"].get("contacts", ()); source_rows = _diagnostic_rows(paths["source"], colliders)
    return {"fiber": record.get("fiber", ""), "radius": radius,
            "pin_indices": record["request"].get("pin_indices", ()),
            "stored": _clearance_curve(paths["source"], source_rows, colliders, radius, contacts),
            "corrected": _clearance_curve(paths["v25"], corrected_rows, colliders, radius, contacts)}


def _build(record, colliders, output_dir, blend_output):
    paths = _paths(record); radius = max(float(record.get("collision_radius", .002)), .002)
    owners = tuple(dict.fromkeys(record["request"]["owners"])); bounds = _focus(paths, radius); center = sum(bounds) * .5
    scale = max(float(np.max(bounds[1] - bounds[0])) * 1.18, radius * 20.0); _reset(); materials = _materials(owners)
    _build_surfaces(colliders, bounds, owners, materials); curves = _build_curves(paths, radius, materials)
    rows = _diagnostic_rows(paths["v25"], colliders); diagnostics, normal = _diagnostic_objects(paths["v25"], radius, rows)
    _pins(record["anchors"], radius * 3.2, materials[3]); _light("KEY", center, (-1, -1, 2), scale, 180)
    _light("FILL", center, (1, 1, 1), scale, 70); cameras = _cameras(center, scale, normal)
    closeups = _closeup_cameras(paths["v25"], rows, radius, record["request"]["pin_indices"])
    _render_views(output_dir, cameras, closeups, curves, diagnostics)
    if blend_output: bpy.ops.wm.save_as_mainfile(filepath=str(Path(blend_output).resolve()), check_existing=False, copy=True)
    return _diagnostic_payload(paths, colliders, radius, rows, record)


def _cameras(center, scale, normal):
    return {"front": _camera("FRONT", center, (0, -1, 0), scale),
            "side": _camera("SIDE", center, (1, 0, 0), scale),
            "top": _camera("TOP", center, (0, 0, 1), scale),
            "surface_normal": _camera("SURFACE_NORMAL", center, normal, scale)}


def main():
    args = _args(); record = json.loads(Path(args.input).read_text(encoding="utf-8")); _ensure_addon()
    colliders = _capture(); output_dir = Path(args.output_dir).resolve(); output_dir.mkdir(parents=True, exist_ok=True)
    diagnostic = _build(record, colliders, output_dir, args.blend_output)
    (output_dir / "clearance_diagnostics.json").write_text(json.dumps(diagnostic, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

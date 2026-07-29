import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree


@dataclass(frozen=True)
class Guide:
    name: str
    fiber_id: str
    closed: bool
    points: np.ndarray


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--target-faces", type=int, default=24000)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def ensure_runtime():
    import anthroforge
    if not hasattr(bpy.types.Object, "af_vcp_system"):
        anthroforge.register()
    from anthroforge.adapters.draft_skin.vendor import ensure_worker_dependencies
    ensure_worker_dependencies()


def scene_inputs():
    root = next((obj for obj in bpy.data.objects if obj.get("anthroforge_root")), None)
    skin = next((obj for obj in bpy.data.objects if obj.get("af_draft_skin")), None)
    if root is None or skin is None:
        raise RuntimeError("The scene needs AF_ROOT and AF_DRAFT_SKIN.")
    return root, skin


def guide_modes(root):
    return {str(item.id): str(item.topology_mode) for item in root.af_vcp_system.fibers}


def collect_guides(root):
    modes = guide_modes(root)
    objects = [obj for obj in bpy.data.objects if obj.get("af_fiber_proxy")]
    guides = [_guide_from_object(obj, modes) for obj in sorted(objects, key=lambda item: item.name)]
    return tuple(guide for guide in guides if guide is not None)


def _guide_from_object(obj, modes):
    fiber_id = str(obj.get("af_fiber_id") or "")
    points = _curve_points(obj)
    if fiber_id not in modes or len(points) < 2:
        return None
    return Guide(obj.name, fiber_id, modes[fiber_id] == "LOOP", points)


def _curve_points(obj):
    splines = tuple(getattr(obj.data, "splines", ()))
    if not splines:
        return np.empty((0, 3), dtype=np.float64)
    points = tuple(getattr(splines[0], "points", ()))
    world = [obj.matrix_world @ Vector(point.co[:3]) for point in points]
    return np.asarray(world, dtype=np.float64)


def make_collection(name, parent=None):
    collection = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(collection)
    return collection


def duplicate_work_mesh(skin, target_faces, collection):
    work = skin.copy()
    work.data = skin.data.copy()
    work.name = "AF_TOPO_WORK_SURFACE"
    collection.objects.link(work)
    _decimate(work, target_faces)
    work.hide_render = True
    work.hide_viewport = True
    return work


def _decimate(obj, target_faces):
    ratio = min(1.0, max(0.01, float(target_faces) / max(1, len(obj.data.polygons))))
    modifier = obj.modifiers.new("AF_TOPO_DECIMATE", "DECIMATE")
    modifier.ratio = ratio
    _activate(obj)
    bpy.ops.object.modifier_apply(modifier=modifier.name)


def _activate(obj):
    for item in tuple(bpy.context.selected_objects):
        item.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def mesh_arrays(obj):
    mesh = obj.data
    mesh.calc_loop_triangles()
    vertices = np.asarray([obj.matrix_world @ vertex.co for vertex in mesh.vertices])
    faces = np.asarray([triangle.vertices[:] for triangle in mesh.loop_triangles], dtype=np.int32)
    normals = np.asarray([_world_normal(obj, vertex.normal) for vertex in mesh.vertices])
    return vertices.astype(np.float64), faces, _normalize(normals)


def _world_normal(obj, normal):
    matrix = obj.matrix_world.to_3x3().inverted().transposed()
    return matrix @ normal


def surface_bvh(vertices, faces):
    return BVHTree.FromPolygons(vertices.tolist(), faces.tolist(), all_triangles=True)


def tangent_bases(normals):
    first = _project_vectors(np.tile((1.0, 0.0, 0.0), (len(normals), 1)), normals)
    weak = np.linalg.norm(first, axis=1) < 1.0e-5
    first[weak] = _project_vectors(np.tile((0.0, 0.0, 1.0), (weak.sum(), 1)), normals[weak])
    first = _normalize(first)
    return first, _normalize(np.cross(normals, first))


def _project_vectors(vectors, normals):
    return vectors - (np.sum(vectors * normals, axis=1)[:, None] * normals)


def _normalize(values):
    lengths = np.linalg.norm(values, axis=1)
    lengths[lengths < 1.0e-12] = 1.0
    return values / lengths[:, None]


def projected_guide(guide, bvh):
    hits = [_nearest(bvh, point) for point in guide.points]
    valid = [hit for hit in hits if hit is not None]
    if len(valid) != len(guide.points):
        return None
    points = np.asarray([hit[0] for hit in valid])
    normals = _normalize(np.asarray([hit[1] for hit in valid]))
    faces = np.asarray([hit[2] for hit in valid], dtype=np.int32)
    return points, normals, faces


def _nearest(bvh, point):
    hit = bvh.find_nearest(Vector(point))
    return None if hit is None or hit[0] is None else (tuple(hit[0]), tuple(hit[1]), int(hit[2]))


def constraint_rows(guides, include_open, bvh, vertices, faces, normals, bases):
    rows = []
    for guide in guides:
        if guide.closed or include_open:
            rows.extend(_guide_rows(guide, bvh, vertices, faces, normals, bases))
    return rows


def _guide_rows(guide, bvh, vertices, faces, normals, bases):
    projected = projected_guide(guide, bvh)
    if projected is None:
        return []
    points, _hit_normals, face_ids = projected
    tangents = _polyline_tangents(points, guide.closed)
    weight = 30.0 if guide.closed else 8.0
    return [_constraint_row(face_ids[i], points[i], tangents[i], vertices, faces, normals, bases, weight) for i in range(len(points))]


def _polyline_tangents(points, closed):
    if closed:
        return _normalize(np.roll(points, -1, axis=0) - np.roll(points, 1, axis=0))
    tangents = np.gradient(points, axis=0)
    return _normalize(np.asarray(tangents))


def _constraint_row(face_id, point, tangent, vertices, faces, normals, bases, weight):
    candidates = faces[int(face_id)]
    index = int(candidates[np.argmin(np.linalg.norm(vertices[candidates] - point, axis=1))])
    tangent = tangent - (np.dot(tangent, normals[index]) * normals[index])
    angle = math.atan2(np.dot(tangent, bases[1][index]), np.dot(tangent, bases[0][index]))
    return index, complex(math.cos(4.0 * angle), math.sin(4.0 * angle)), float(weight)


def solve_field(vertices, faces, rows):
    sparse, graph = _scipy_modules()
    laplacian = graph.laplacian(_adjacency(len(vertices), faces, sparse), normed=False)
    weights, targets = _constraint_arrays(len(vertices), rows)
    matrix = laplacian + sparse.diags(weights)
    real = sparse.linalg.spsolve(matrix, targets.real)
    imag = sparse.linalg.spsolve(matrix, targets.imag)
    raw = real + (1j * imag)
    return raw / np.maximum(np.abs(raw), 1.0e-12), raw


def _scipy_modules():
    from scipy import sparse
    from scipy.sparse import csgraph
    return sparse, csgraph


def _adjacency(count, faces, sparse):
    first = np.concatenate((faces[:, 0], faces[:, 1], faces[:, 2]))
    second = np.concatenate((faces[:, 1], faces[:, 2], faces[:, 0]))
    rows, cols = np.concatenate((first, second)), np.concatenate((second, first))
    matrix = sparse.coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(count, count)).tocsr()
    matrix.data[:] = 1.0
    return matrix


def _constraint_arrays(count, rows):
    weights = np.full(count, 0.025, dtype=np.float64)
    targets = np.full(count, 0.025 + 0.0j, dtype=np.complex128)
    for index, value, weight in rows:
        weights[index] += weight
        targets[index] += weight * value
    return weights, targets


def field_directions(field, bases):
    angles = np.angle(field) * 0.25
    return _normalize((np.cos(angles)[:, None] * bases[0]) + (np.sin(angles)[:, None] * bases[1]))


def field_metrics(field, raw, rows, faces):
    errors = [_angular_error(field[index], value) for index, value, _weight in rows]
    differences = _edge_differences(field, faces)
    return {
        "constraints": len(rows),
        "mean_alignment_degrees": float(np.degrees(np.mean(errors))) if errors else 0.0,
        "p95_alignment_degrees": float(np.degrees(np.quantile(errors, 0.95))) if errors else 0.0,
        "mean_neighbor_cross_delta": float(np.mean(differences)),
        "weak_field_vertices": int(np.count_nonzero(np.abs(raw) < 0.2)),
    }


def _angular_error(first, second):
    difference = abs(np.angle(first * np.conjugate(second))) * 0.25
    return min(difference, (math.pi * 0.5) - difference)


def _edge_differences(field, faces):
    first = np.concatenate((faces[:, 0], faces[:, 1], faces[:, 2]))
    second = np.concatenate((faces[:, 1], faces[:, 2], faces[:, 0]))
    return np.abs(field[first] - field[second])


def material(name, color, emission=0.0):
    value = bpy.data.materials.new(name)
    value.diffuse_color = (*color, 1.0)
    value.use_nodes = True
    shader = value.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1.0)
    shader.inputs["Roughness"].default_value = 0.5
    _set_emission(shader, color, emission)
    return value


def _set_emission(shader, color, strength):
    if "Emission Color" in shader.inputs:
        shader.inputs["Emission Color"].default_value = (*color, 1.0)
        shader.inputs["Emission Strength"].default_value = float(strength)


def curve_object(name, polylines, collection, value, bevel):
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"
    data.bevel_depth = float(bevel)
    data.bevel_resolution = 1
    for points, cyclic in polylines:
        _add_spline(data, points, cyclic)
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.data.materials.append(value)
    return obj


def _add_spline(data, points, cyclic):
    if len(points) < 2:
        return
    spline = data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    spline.points.foreach_set("co", np.column_stack((points, np.ones(len(points)))).ravel())
    spline.use_cyclic_u = bool(cyclic)


def guide_lines(guides, bvh, offset):
    result = []
    for guide in guides:
        projected = projected_guide(guide, bvh)
        if projected is not None:
            result.append((projected[0] + (projected[1] * offset), guide.closed))
    return result


def loop_bands(guides, bvh, spacing, offset):
    lines = []
    for guide in guides:
        if guide.closed:
            lines.extend(_guide_bands(guide, bvh, spacing, offset))
    return lines


def _guide_bands(guide, bvh, spacing, offset):
    projected = projected_guide(guide, bvh)
    if projected is None:
        return []
    points, normals, _faces = projected
    tangents = _polyline_tangents(points, True)
    sides = _normalize(np.cross(normals, tangents))
    return [(_offset_band(points, normals, sides, distance, bvh, offset), True) for distance in (-spacing, 0.0, spacing)]


def _offset_band(points, normals, sides, distance, bvh, offset):
    seeds = points + (sides * float(distance))
    hits = [_nearest(bvh, point) for point in seeds]
    locations = np.asarray([hit[0] for hit in hits])
    hit_normals = _normalize(np.asarray([hit[1] for hit in hits]))
    return locations + (hit_normals * offset)


def cross_lines(vertices, normals, directions, mask, length, offset, limit=1200):
    indices = np.flatnonzero(mask)
    indices = indices[::max(1, int(math.ceil(len(indices) / limit)))]
    centers = vertices[indices] + (normals[indices] * offset)
    first = directions[indices] * (length * 0.5)
    second = _normalize(np.cross(normals[indices], directions[indices])) * (length * 0.5)
    return [(np.asarray((center - a, center + a)), False) for center, a in zip(centers, first)] + [
        (np.asarray((center - b, center + b)), False) for center, b in zip(centers, second)
    ]


def facial_mask(vertices, normals):
    front = normals[:, 1] < -0.15
    height = (vertices[:, 2] > 0.15) & (vertices[:, 2] < 1.75)
    width = np.abs(vertices[:, 0]) < 0.95
    return front & height & width


def create_visuals(skin, guides, bvh, vertices, normals, loop_field, all_field, root_collection):
    materials = _visual_materials(skin)
    collections = _visual_collections(root_collection)
    _create_guides(guides, bvh, materials, collections)
    mask = facial_mask(vertices, normals)
    _create_field("AF_TOPO_LOOP_FIELD", loop_field, vertices, normals, mask, materials["field"], collections["loop_field"])
    _create_field("AF_TOPO_ALL_FIELD", all_field, vertices, normals, mask, materials["field"], collections["all_field"])
    return collections


def _visual_materials(skin):
    skin.data.materials.clear()
    skin.data.materials.append(material("AF_TOPO_SKIN", (0.12, 0.16, 0.21)))
    return {
        "loop": material("AF_TOPO_LOOP", (1.0, 0.08, 0.04), 2.0),
        "open": material("AF_TOPO_OPEN", (1.0, 0.42, 0.04), 1.5),
        "band": material("AF_TOPO_BAND", (0.18, 1.0, 0.28), 2.0),
        "field": material("AF_TOPO_FIELD", (0.05, 0.75, 1.0), 1.8),
    }


def _visual_collections(parent):
    names = ("loop", "open", "bands", "loop_field", "all_field")
    return {name: make_collection(f"AF_TOPO_{name.upper()}", parent) for name in names}


def _create_guides(guides, bvh, materials, collections):
    loops = tuple(guide for guide in guides if guide.closed)
    opens = tuple(guide for guide in guides if not guide.closed)
    curve_object("AF_TOPO_LOOP_GUIDES", guide_lines(loops, bvh, 0.006), collections["loop"], materials["loop"], 0.0045)
    curve_object("AF_TOPO_OPEN_GUIDES", guide_lines(opens, bvh, 0.005), collections["open"], materials["open"], 0.0025)
    curve_object("AF_TOPO_LOOP_BANDS", loop_bands(loops, bvh, 0.025, 0.008), collections["bands"], materials["band"], 0.003)


def _create_field(name, directions, vertices, normals, mask, value, collection):
    lines = cross_lines(vertices, normals, directions, mask, 0.045, 0.009)
    curve_object(name, lines, collection, value, 0.0014)


def prepare_render(skin):
    for obj in tuple(bpy.context.scene.objects):
        obj.hide_render = obj != skin
    _render_settings()
    camera = _camera()
    _lights()
    return camera


def _render_settings():
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x, scene.render.resolution_y = 720, 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.world.color = (0.004, 0.006, 0.012)
    scene.view_settings.look = "AgX - Medium High Contrast"


def _camera():
    data = bpy.data.cameras.new("AF_TOPO_CAMERA")
    data.type, data.ortho_scale = "ORTHO", 3.25
    camera = bpy.data.objects.new("AF_TOPO_CAMERA", data)
    bpy.context.scene.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    return camera


def _lights():
    _light("AF_TOPO_KEY", (-4.0, -5.0, 6.0), 1200.0, 4.0)
    _light("AF_TOPO_FILL", (4.0, -3.0, 3.0), 700.0, 3.0)
    _light("AF_TOPO_RIM", (0.0, 4.0, 5.0), 900.0, 3.0)


def _light(name, location, energy, size):
    data = bpy.data.lights.new(name, "AREA")
    data.energy, data.shape, data.size = energy, "DISK", size
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    look_at(obj, (0.0, 0.0, 1.25))


def look_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def render_variants(camera, collections, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    variants = _variant_visibility()
    for name, visible in variants.items():
        _set_collections(collections, visible)
        _render_view(camera, (0.0, -8.0, 1.25), folder / f"{name}_front.png")
    _set_collections(collections, variants["all_field"])
    _render_view(camera, (4.6, -7.0, 2.8), folder / "all_field_threequarter.png")
    _contact_sheet(folder, tuple(variants))


def _variant_visibility():
    return {
        "guides": {"loop", "open"},
        "loop_bands": {"loop", "bands"},
        "loop_field": {"loop", "loop_field"},
        "all_field": {"loop", "open", "all_field"},
    }


def _set_collections(collections, visible):
    for name, collection in collections.items():
        collection.hide_render = name not in visible
        for obj in collection.objects:
            obj.hide_render = name not in visible


def _render_view(camera, location, path):
    camera.location = location
    look_at(camera, (0.0, 0.0, 1.2))
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def _contact_sheet(folder, names):
    from PIL import Image, ImageDraw
    images = [Image.open(folder / f"{name}_front.png").convert("RGB") for name in names]
    canvas = Image.new("RGB", (1440, 1440), (5, 8, 14))
    labels = ("Projected generic guides", "Closed-guide candidate bands", "Closed guides - cross field", "All guides - cross field")
    for index, (image, label) in enumerate(zip(images, labels)):
        _paste_panel(canvas, image, label, index)
    canvas.save(folder / "topology_guide_comparison.png")


def _paste_panel(canvas, image, label, index):
    from PIL import ImageDraw
    x, y = (index % 2) * 720, (index // 2) * 720
    canvas.paste(image, (x, y))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((x, y, x + 390, y + 38), fill=(5, 8, 14))
    draw.text((x + 12, y + 10), label, fill=(235, 240, 248))


def write_metrics(path, metrics):
    target = Path(path)
    target.write_text(json.dumps(metrics, indent=2), encoding="utf-8")


def save_result(path, skin, metrics, collections):
    skin["af_topology_prototype_stats"] = json.dumps(metrics, sort_keys=True)
    _set_collections(collections, {"loop", "open", "all_field"})
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True)


def build_fields(guides, bvh, vertices, faces, normals, bases):
    loop_rows = constraint_rows(guides, False, bvh, vertices, faces, normals, bases)
    all_rows = constraint_rows(guides, True, bvh, vertices, faces, normals, bases)
    loop_field, loop_raw = solve_field(vertices, faces, loop_rows)
    all_field, all_raw = solve_field(vertices, faces, all_rows)
    return loop_rows, all_rows, loop_field, loop_raw, all_field, all_raw


def build_prototype(args):
    root, skin = scene_inputs()
    guides = collect_guides(root)
    root_collection = make_collection("AF_TOPOLOGY_TEST")
    work = duplicate_work_mesh(skin, args.target_faces, root_collection)
    vertices, faces, normals = mesh_arrays(work)
    bvh, bases = surface_bvh(vertices, faces), tangent_bases(normals)
    fields = build_fields(guides, bvh, vertices, faces, normals, bases)
    return skin, guides, root_collection, vertices, faces, normals, bvh, bases, fields


def finish_prototype(args, data):
    skin, guides, root_collection, vertices, faces, normals, bvh, bases, fields = data
    loop_rows, all_rows, loop_field, loop_raw, all_field, all_raw = fields
    metrics = _metrics(guides, vertices, faces, loop_field, loop_raw, loop_rows, all_field, all_raw, all_rows)
    collections = create_visuals(skin, guides, bvh, vertices, normals, field_directions(loop_field, bases), field_directions(all_field, bases), root_collection)
    camera = prepare_render(skin)
    render_variants(camera, collections, args.render_dir)
    write_metrics(Path(args.render_dir) / "metrics.json", metrics)
    save_result(args.output, skin, metrics, collections)
    print("AF_TOPOLOGY_PROTOTYPE", json.dumps(metrics, sort_keys=True), flush=True)


def main():
    args = parse_args()
    ensure_runtime()
    finish_prototype(args, build_prototype(args))


def _metrics(guides, vertices, faces, loop_field, loop_raw, loop_rows, all_field, all_raw, all_rows):
    return {
        "source_vertices": int(len(vertices)),
        "source_triangles": int(len(faces)),
        "guides": len(guides),
        "closed_guides": sum(guide.closed for guide in guides),
        "loop_only": field_metrics(loop_field, loop_raw, loop_rows, faces),
        "all_guides": field_metrics(all_field, all_raw, all_rows, faces),
    }


if __name__ == "__main__":
    main()

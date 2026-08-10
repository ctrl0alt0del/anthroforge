import argparse
from dataclasses import dataclass, replace
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


ADDON_ROOT = Path(__file__).resolve().parents[1]
EQUIVALENCE_TOLERANCE = 2.0e-6
if str(ADDON_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT.parent))


@dataclass(frozen=True)
class Variant:
    key: str
    label: str
    legacy: object
    replacement: object


@dataclass(frozen=True)
class BuiltPair:
    variant: Variant
    legacy_object: object
    replacement_object: object
    model: object
    solve_result: object


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-dir", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:])


def reset_and_register():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    import anthroforge
    if not hasattr(bpy.types.Object, "af_scp_system"):
        anthroforge.register()


def make_collection(name):
    collection = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(collection)
    return collection


def make_mesh_object(name, vertices, faces, collection):
    mesh = bpy.data.meshes.new(f"{name}_MESH")
    mesh.from_pydata(vertices, (), faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def host_grid(columns=17, rows=17, half_width=3.2, half_depth=2.6):
    vertices = tuple(_grid_point(x, y, columns, rows, half_width, half_depth)
                     for y in range(rows) for x in range(columns))
    faces = tuple(_grid_face(x, y, columns) for y in range(rows - 1) for x in range(columns - 1))
    return vertices, faces


def _grid_point(x, y, columns, rows, half_width, half_depth):
    px = -half_width + 2.0 * half_width * x / (columns - 1)
    py = -half_depth + 2.0 * half_depth * y / (rows - 1)
    return px, py, 0.0


def _grid_face(x, y, columns):
    first = y * columns + x
    return first, first + 1, first + columns + 1, first + columns


def create_host(collection):
    from anthroforge.core.scp_runtime.object_roles import create_scp, set_scp_geometry_object, set_scp_transform_object
    from anthroforge.core.utils import ensure_af_root
    host = make_mesh_object("AF_CLOSED_BULK_HOST_SCP", *host_grid(), collection)
    root = ensure_af_root(bpy.context.scene)
    scp = create_scp(root, "Closed Bulk Host")
    set_scp_transform_object(root, scp, host)
    set_scp_geometry_object(root, scp, host)
    host["af_soft_tissue_host"] = True
    return root, scp, host


def variants(scp_id):
    from anthroforge.core.vcp.soft_tissue_model import AttachmentMode, AttachmentSpec, TargetKind, TargetSurface
    attachment = AttachmentSpec(TargetKind.SCP, scp_id, TargetSurface.SCP_GEOMETRY,
                                AttachmentMode.FIXED, 1.0)
    return (_variant("SPHERE", "Sphere", 1.45, 0.72, "SPHERE", (1.0, 1.0, 1.0), 0.0),
            _variant("ELLIPSOID", "Ellipsoid", 0.0, 0.78, "ELLIPSOID", (1.3, 0.82, 1.35), 0.0),
            _variant("SAG", "Attached + Sag", -1.45, 0.54, "ELLIPSOID",
                     (1.18, 0.86, 1.36), 0.75, attachment))


def _variant(key, label, y, z, shape, scale, sag, attachment=None):
    from anthroforge.core.vcp.soft_tissue_closed_bulk import LegacyBlobSpec
    legacy = LegacyBlobSpec(f"BLOB_REFERENCE_{key}", f"Legacy {label}", (-1.25, y, z),
                            0.46, shape, scale, 64, (0.0, 0.0, -1.0), sag, 0.28,
                            0.38, 80, attachment or _free_attachment())
    replacement = replace(legacy, id=f"SOFT_TISSUE_CLOSED_BULK_{key}",
                          name=f"Closed Bulk {label}", center=(1.25, y, z))
    return Variant(key, label, legacy, replacement)


def _free_attachment():
    from anthroforge.core.vcp.soft_tissue_model import AttachmentSpec
    return AttachmentSpec()


def add_legacy_blob(root, spec):
    prop = root.af_vcp_system.blobs.add()
    _set_blob_identity(prop, spec)
    _set_blob_geometry(prop, spec)
    _set_blob_relaxation(prop, spec)
    _set_blob_attachment(prop, spec)
    return prop


def add_legacy_blobs(root, items):
    from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
    with suppress_vcp_prop_updates():
        return tuple(add_legacy_blob(root, item.legacy) for item in items)


def _set_blob_identity(prop, spec):
    prop.id, prop.name = spec.id, spec.name


def _set_blob_geometry(prop, spec):
    prop.center_world, prop.radius, prop.shape = spec.center, spec.radius, spec.shape
    prop.axis_scale, prop.resolution = spec.axis_scale, spec.resolution
    prop.control_point_world = spec.center


def _set_blob_relaxation(prop, spec):
    prop.gravity_dir, prop.sag_strength = spec.gravity, spec.sag_strength
    prop.sag_limit, prop.stiffness, prop.iterations = spec.sag_limit, spec.stiffness, spec.iterations


def _set_blob_attachment(prop, spec):
    target = spec.attachment
    prop.attach_target_type = target.target_kind.value
    prop.attach_target_id = target.target_id
    prop.attach_target_object_name = ""


def sync_legacy_blobs(root):
    from anthroforge.core.visualization.blob_sync import register_blob_sync, unregister_blob_sync
    root.af_vcp_system.active_vcp_type, root.af_vcp_system.active_vcp_id = "NONE", ""
    bpy.context.view_layer.update()
    _require_legacy_targets(root)
    sync = register_blob_sync()
    _restore_legacy_transforms(sync, root)
    sync.sync_root_to_scene(root=root, scene=bpy.context.scene)
    bpy.context.view_layer.update()
    sync.sync_root_to_scene(root=root, scene=bpy.context.scene)
    unregister_blob_sync()


def _require_legacy_targets(root):
    from anthroforge.core.visualization.blob_sync_helpers import target_object_for_blob
    for prop in root.af_vcp_system.blobs:
        if prop.attach_target_type == "NONE":
            continue
        if target_object_for_blob(bpy.context.scene, root, prop) is None:
            raise RuntimeError(f"Legacy Blob target does not resolve for {prop.id}.")


def _restore_legacy_transforms(sync, root):
    collection = bpy.context.scene.collection.children.get("AF_VCP_VIS")
    if collection is None:
        return
    for prop in root.af_vcp_system.blobs:
        obj = sync._find_blob_proxy(collection, root.name, prop.id)
        if obj is not None:
            sync._apply_initial_transform_from_prop(obj, prop)


def legacy_proxy(root, blob_id):
    from anthroforge.core.visualization.blob_sync_helpers import find_blob_proxy
    collection = bpy.context.scene.collection.children.get("AF_VCP_VIS")
    result = None if collection is None else find_blob_proxy(collection, root.name, blob_id)
    if result is None:
        raise RuntimeError(f"Legacy Blob proxy {blob_id} was not created.")
    return result


def create_replacement(spec, host, collection, value):
    from anthroforge.core.vcp.soft_tissue_closed_bulk import closed_bulk_model_from_legacy, legacy_spec_from_closed_bulk
    model = closed_bulk_model_from_legacy(spec)
    mapped = legacy_spec_from_closed_bulk(model)
    obj, result = _solve_replacement(mapped, host, collection)
    obj.data.materials.append(value)
    _smooth_mesh(obj)
    _tag_replacement(obj, model, spec)
    return obj, model, result


def _solve_replacement(spec, host, collection):
    from anthroforge.core.visualization.blob_sync_helpers import unit_local_mesh
    from anthroforge.core.vcp.blob_solver import BlobSolver
    runtime = _runtime_from_spec(spec)
    unit, faces = unit_local_mesh(runtime)
    rest = tuple(_rest_point(point, spec) for point in unit)
    target = host if spec.attachment.target_id else None
    result = BlobSolver().solve(runtime, target, rest, faces)
    obj = make_mesh_object(f"AF_{spec.id}", result.points, faces, collection)
    return obj, result


def _runtime_from_spec(spec):
    from anthroforge.core.vcp.blob import BlobVCPRuntime
    target = spec.attachment
    return BlobVCPRuntime(spec.id, spec.name, Vector(spec.center), spec.radius, spec.shape,
                          Vector(spec.axis_scale), spec.resolution, Vector(spec.gravity),
                          spec.sag_strength, spec.sag_limit, target.target_kind.value,
                          target.target_id, "", Vector(spec.center), spec.stiffness, spec.iterations)


def _rest_point(point, spec):
    scale = spec.axis_scale if spec.shape == "ELLIPSOID" else (1.0, 1.0, 1.0)
    scaled = Vector((point.x * scale[0], point.y * scale[1], point.z * scale[2])) * spec.radius
    return Vector(spec.center) + scaled


def _tag_replacement(obj, model, spec):
    from anthroforge.core.vcp.soft_tissue_model import model_to_dict, validate_model
    errors = validate_model(model)
    if errors:
        raise RuntimeError("; ".join(errors))
    obj["af_soft_tissue_vcp"] = True
    obj["af_soft_tissue_id"] = model.id
    obj["af_soft_tissue_model"] = json.dumps(model_to_dict(model), separators=(",", ":"))
    obj["af_replaces_blob_controls"] = json.dumps(_control_payload(spec), separators=(",", ":"))


def _control_payload(spec):
    return {"center_world": spec.center, "radius": spec.radius, "shape": spec.shape,
            "axis_scale": spec.axis_scale, "resolution": spec.resolution,
            "gravity_dir": spec.gravity, "sag_strength": spec.sag_strength,
            "sag_limit": spec.sag_limit, "stiffness": spec.stiffness,
            "iterations": spec.iterations}


def _smooth_mesh(obj):
    for polygon in obj.data.polygons:
        polygon.use_smooth = True


def build_pairs(root, host, items, collection, materials):
    pairs = []
    for item in items:
        legacy = legacy_proxy(root, item.legacy.id)
        _style_legacy(legacy, materials["legacy"])
        replacement, model, result = create_replacement(item.replacement, host, collection, materials["replacement"])
        pairs.append(BuiltPair(item, legacy, replacement, model, result))
    return tuple(pairs)


def _style_legacy(obj, value):
    obj.data.materials.clear()
    obj.data.materials.append(value)
    _smooth_mesh(obj)
    obj["af_closed_bulk_reference"] = True


def create_overlays(pairs, collection, value):
    return tuple(_create_overlay(pair, collection, value) for pair in pairs)


def _create_overlay(pair, collection, value):
    vertices = _aligned_replacement_vertices(pair)
    faces = tuple(tuple(vertex for vertex in polygon.vertices) for polygon in pair.replacement_object.data.polygons)
    obj = make_mesh_object(f"AF_EQUIVALENCE_{pair.variant.key}", vertices, faces, collection)
    obj.data.materials.append(value)
    modifier = obj.modifiers.new("AF_EQUIVALENCE_WIRE", "WIREFRAME")
    modifier.thickness, modifier.use_replace = 0.006, True
    obj.hide_render = obj.hide_viewport = True
    return obj


def _aligned_replacement_vertices(pair):
    source = world_vertices(pair.replacement_object)
    first, second = pair.variant.legacy.center, pair.variant.replacement.center
    offset = tuple(first[index] - second[index] for index in range(3))
    return tuple(tuple(point[index] + offset[index] for index in range(3)) for point in source)


def material(name, color, metallic=0.0, roughness=0.5, emission=0.0):
    value = bpy.data.materials.new(name)
    value.diffuse_color = (*color, 1.0)
    value.use_nodes = True
    node = value.node_tree.nodes.get("Principled BSDF")
    node.inputs["Base Color"].default_value = (*color, 1.0)
    node.inputs["Metallic"].default_value = metallic
    node.inputs["Roughness"].default_value = roughness
    node.inputs["Emission Color"].default_value = (*color, 1.0)
    node.inputs["Emission Strength"].default_value = emission
    return value


def experiment_materials():
    return {"legacy": material("AF_LEGACY_BLOB_MAT", (0.82, 0.31, 0.08), roughness=0.46),
            "replacement": material("AF_CLOSED_BULK_MAT", (0.08, 0.62, 0.92), roughness=0.42),
            "host": material("AF_CLOSED_BULK_HOST_MAT", (0.18, 0.23, 0.31), roughness=0.78),
            "overlay": material("AF_EQUIVALENCE_MAT", (0.2, 1.0, 0.38), roughness=0.25, emission=2.5)}


def world_vertices(obj):
    return tuple(tuple(obj.matrix_world @ vertex.co) for vertex in obj.data.vertices)


def pair_metrics(pair):
    legacy = world_vertices(pair.legacy_object)
    aligned = _aligned_replacement_vertices(pair)
    errors = tuple(_distance(first, second) for first, second in zip(legacy, aligned))
    volume_error = _relative_volume_error(pair.legacy_object, pair.replacement_object)
    return {"key": pair.variant.key, "legacy_blob_id": pair.variant.legacy.id,
            "closed_bulk_id": pair.model.id, "attached_to_scp": bool(pair.model.attachments),
            "vertex_count": len(legacy), "max_vertex_error": max(errors),
            "rms_vertex_error": math.sqrt(sum(value * value for value in errors) / len(errors)),
            "relative_volume_error": volume_error,
            "equivalent": max(errors) < EQUIVALENCE_TOLERANCE and volume_error < EQUIVALENCE_TOLERANCE}


def _relative_volume_error(first, second):
    from anthroforge.core.vcp.soft_tissue_static_pouch import mesh_volume, triangulate_faces
    first_faces = tuple(tuple(vertex for vertex in face.vertices) for face in first.data.polygons)
    second_faces = tuple(tuple(vertex for vertex in face.vertices) for face in second.data.polygons)
    first_volume = abs(mesh_volume(world_vertices(first), triangulate_faces(first_faces)))
    second_volume = abs(mesh_volume(world_vertices(second), triangulate_faces(second_faces)))
    return abs(second_volume - first_volume) / max(first_volume, 1.0e-12)


def _distance(first, second):
    return sum((float(first[index]) - float(second[index])) ** 2 for index in range(3)) ** 0.5


def metrics_payload(root, scp, host, before, pairs):
    rows = tuple(pair_metrics(pair) for pair in pairs)
    return {"host_scp_id": scp.id, "host_object": host.name,
            "topology_preserved": before == _host_signature(host),
            "legacy_blob_count": len(root.af_vcp_system.blobs),
            "closed_bulk_count": len(pairs), "all_equivalent": all(row["equivalent"] for row in rows),
            "max_vertex_error": max(row["max_vertex_error"] for row in rows), "variants": rows}


def _host_signature(host):
    from anthroforge.core.scp_proxy.signature import topology_signature
    return topology_signature(bpy.context.scene, host)


def make_camera():
    data = bpy.data.cameras.new("AF_CLOSED_BULK_CAMERA")
    data.type, data.ortho_scale = "ORTHO", 6.3
    camera = bpy.data.objects.new("AF_CLOSED_BULK_CAMERA", data)
    bpy.context.scene.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    return camera


def point_at(obj, target=(0.0, 0.0, 0.25)):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def add_light(name, location, energy, size):
    data = bpy.data.lights.new(name, "AREA")
    data.energy, data.shape, data.size = energy, "DISK", size
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    point_at(obj)


def configure_render():
    scene = bpy.context.scene
    _set_eevee(scene)
    scene.render.resolution_x, scene.render.resolution_y = 900, 760
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.world = scene.world or bpy.data.worlds.new("AF_CLOSED_BULK_WORLD")
    scene.world.color = (0.008, 0.012, 0.02)
    add_light("AF_CLOSED_BULK_KEY", (-4.0, -4.0, 7.0), 1200.0, 3.8)
    add_light("AF_CLOSED_BULK_FILL", (4.5, 2.5, 5.0), 850.0, 3.2)


def _set_eevee(scene):
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            return
        except TypeError:
            continue


def render_experiment(folder, camera, pairs, overlays):
    folder.mkdir(parents=True, exist_ok=True)
    camera.location = (5.4, -7.2, 6.3)
    point_at(camera)
    _render(folder / "closed_bulk_comparison.png")
    _set_overlay_visibility(pairs, overlays, True)
    _render(folder / "closed_bulk_equivalence_overlay.png")
    _set_overlay_visibility(pairs, overlays, False)
    camera.location = (4.3, -5.8, 2.3)
    point_at(camera, (0.0, -1.45, 0.3))
    _render(folder / "closed_bulk_attached_sag.png")


def _set_overlay_visibility(pairs, overlays, enabled):
    for pair in pairs:
        pair.replacement_object.hide_render = enabled
    for overlay in overlays:
        overlay.hide_render = not enabled
        overlay.hide_viewport = not enabled


def _render(path):
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def build_experiment():
    collection = make_collection("AF_SOFT_TISSUE_CLOSED_BULK_EXPERIMENT")
    debug = make_collection("AF_SOFT_TISSUE_CLOSED_BULK_DEBUG")
    root, scp, host = create_host(collection)
    before = _host_signature(host)
    items, materials = variants(scp.id), experiment_materials()
    add_legacy_blobs(root, items)
    sync_legacy_blobs(root)
    pairs = build_pairs(root, host, items, collection, materials)
    host.data.materials.append(materials["host"])
    overlays = create_overlays(pairs, debug, materials["overlay"])
    return root, scp, host, before, pairs, overlays


def finish(args, data):
    root, scp, host, before, pairs, overlays = data
    configure_render()
    render_folder = Path(args.render_dir).resolve()
    render_experiment(render_folder, make_camera(), pairs, overlays)
    metrics = metrics_payload(root, scp, host, before, pairs)
    _save_artifacts(args, root, metrics)
    print("AF_SOFT_TISSUE_CLOSED_BULK_PROTOTYPE", json.dumps(metrics, sort_keys=True), flush=True)


def _save_artifacts(args, root, metrics):
    output = Path(args.output).resolve()
    folder = Path(args.render_dir).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    root["af_soft_tissue_closed_bulk_experiment"] = json.dumps(metrics, separators=(",", ":"))
    (folder / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=str(output), copy=True)


def main():
    args = parse_args()
    reset_and_register()
    finish(args, build_experiment())


if __name__ == "__main__":
    main()

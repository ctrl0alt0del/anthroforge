import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


ADDON_ROOT = Path(__file__).resolve().parents[1]
if str(ADDON_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT.parent))


@dataclass(frozen=True)
class PatchGeometry:
    points: tuple
    faces: tuple
    boundary_edges: tuple
    weights: tuple


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--rings", type=int, default=8)
    parser.add_argument("--segments", type=int, default=48)
    parser.add_argument("--relaxation-mode", choices=("NONE", "GEOMETRIC", "STATIC_PBD"),
                        default="GEOMETRIC")
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


def grid_geometry(columns=17, rows=21, half_width=1.5, half_height=1.8):
    vertices = tuple(_grid_point(x, y, columns, rows, half_width, half_height)
                     for y in range(rows) for x in range(columns))
    faces = tuple(_grid_face(x, y, columns) for y in range(rows - 1) for x in range(columns - 1))
    return vertices, faces


def _grid_point(x, y, columns, rows, half_width, half_height):
    px = -half_width + 2.0 * half_width * x / (columns - 1)
    py = -half_height + 2.0 * half_height * y / (rows - 1)
    return px, py, 0.0


def _grid_face(x, y, columns):
    first = y * columns + x
    return first, first + 1, first + columns + 1, first + columns


def create_host(collection):
    from anthroforge.core.scp_runtime.object_roles import create_scp, set_scp_geometry_object, set_scp_transform_object
    from anthroforge.core.utils import ensure_af_root
    host = make_mesh_object("AF_ABDOMEN_HOST_PLANE", *grid_geometry(), collection)
    root = ensure_af_root(bpy.context.scene)
    scp = create_scp(root, "Abdominal Wall Host")
    set_scp_transform_object(root, scp, host)
    set_scp_geometry_object(root, scp, host)
    host["af_soft_tissue_host"] = True
    return root, scp, host


def patch_geometry(rings, segments):
    rings, segments = max(2, int(rings)), max(8, int(segments))
    rows = tuple(_patch_ring(ring, rings, segments) for ring in range(1, rings + 1))
    points = ((0.0, -0.18, 0.0),) + tuple(point for row in rows for point in row)
    weights = (1.0,) + tuple(_patch_weight(ring, rings, index, segments)
                             for ring in range(1, rings + 1) for index in range(segments))
    faces = _center_faces(segments) + _ring_faces(rings, segments)
    boundary = _outer_boundary(rings, segments)
    return PatchGeometry(points, faces, boundary, weights)


def _patch_ring(ring, rings, segments):
    radius = ring / rings
    return tuple(_patch_point(radius, 2.0 * math.pi * index / segments) for index in range(segments))


def _patch_point(radius, angle):
    x = 0.98 * radius * math.cos(angle)
    y = -0.18 + 1.28 * radius * math.sin(angle)
    return x, y, 0.0


def _patch_weight(ring, rings, index, segments):
    radius = ring / rings
    angle = 2.0 * math.pi * index / segments
    envelope = max(0.0, math.cos(0.5 * math.pi * radius)) ** 1.15
    lower_bias = 1.0 + 0.22 * max(0.0, -math.sin(angle)) * (1.0 - radius)
    return min(1.0, envelope * lower_bias)


def _center_faces(segments):
    return tuple((0, 1 + index, 1 + (index + 1) % segments) for index in range(segments))


def _ring_faces(rings, segments):
    return tuple(_ring_face(ring, index, segments) for ring in range(2, rings + 1)
                 for index in range(segments))


def _ring_face(ring, index, segments):
    inner = 1 + (ring - 2) * segments
    outer = 1 + (ring - 1) * segments
    nxt = (index + 1) % segments
    return inner + index, outer + index, outer + nxt, inner + nxt


def _outer_boundary(rings, segments):
    start = 1 + (rings - 1) * segments
    return tuple((start + index, start + (index + 1) % segments) for index in range(segments))


def capture_bindings(root, scp, patch):
    from anthroforge.core.vcp.attachment_backend import attachment_runtime, capture_attachment_from_world
    runtime = attachment_runtime(bpy.context.scene)
    values = tuple(capture_attachment_from_world(root, bpy.context.scene, scp.id, Vector(point), runtime)
                   for point in patch.points)
    if any(value is None for value in values):
        raise RuntimeError(f"Could not bind abdominal patch to {scp.id}.")
    return values


def deform_host(host):
    for vertex in host.data.vertices:
        x, y = float(vertex.co.x), float(vertex.co.y)
        lateral = 0.11 * (1.0 - 0.55 * (x / 1.5) ** 2)
        vertical = 0.045 * (1.0 - 0.35 * (y / 1.8) ** 2)
        belly = 0.09 * math.exp(-((x / 0.95) ** 2 + ((y + 0.38) / 1.05) ** 2))
        vertex.co.z = lateral + vertical + belly
    host.data.update()
    bpy.context.view_layer.update()


def resolve_bindings(root, scp, bindings):
    from anthroforge.core.vcp.attachment_backend import attachment_runtime, resolve_attachment_normal, resolve_attachment_world
    runtime = attachment_runtime(bpy.context.scene)
    points = tuple(resolve_attachment_world(root, bpy.context.scene, scp.id, raw, runtime) for raw in bindings)
    normals = tuple(resolve_attachment_normal(root, bpy.context.scene, scp.id, raw, runtime) for raw in bindings)
    if any(value is None for value in points + normals):
        raise RuntimeError(f"A binding no longer resolves on {scp.id}.")
    return tuple(tuple(point) for point in points), tuple(tuple(normal) for normal in normals)


def make_base_patch(patch, points, bindings, collection, value):
    obj = make_mesh_object("AF_ABDOMINAL_FAT_BASE_SURFACE", points, patch.faces, collection)
    obj.data.materials.append(value)
    obj["af_soft_tissue_base"] = True
    obj["af_surface_bindings"] = _binding_json(bindings)
    _weighted_group(obj, "AF_ST_THICKNESS", range(len(points)), patch.weights)
    modifier = obj.modifiers.new("AF_BASE_WIREFRAME", "WIREFRAME")
    modifier.thickness, modifier.use_replace = 0.008, True
    return obj


def _binding_json(bindings):
    return json.dumps([json.loads(raw) for raw in bindings], separators=(",", ":"))


def create_tissue(name, mode, base, patch, points, normals, scp, collection, value):
    result = _abdominal_pipeline(mode, patch, points, normals)
    geometry = result.rest
    obj = make_mesh_object(name, result.final_vertices, geometry.faces, collection)
    obj.data.materials.append(value)
    _smooth_mesh(obj)
    _add_tissue_groups(obj, geometry, patch)
    _tag_tissue(obj, name, mode, base, scp)
    return obj, result


def _abdominal_pipeline(mode, patch, points, normals):
    from anthroforge.core.vcp.soft_tissue_static_pouch import StaticPouchSettings
    from anthroforge.core.vcp.soft_tissue_surface_inflation import SurfaceLayerProfile
    from anthroforge.core.vcp.soft_tissue_surface_pipeline import GeometricRelaxationSpec
    from anthroforge.core.vcp.soft_tissue_surface_pipeline import SurfaceTissuePipelineSpec, run_surface_tissue_pipeline
    from anthroforge.core.vcp.soft_tissue_surface_pipeline import surface_fixed_indices
    profile = SurfaceLayerProfile(0.28, 0.008, 0.78)
    geometric = GeometricRelaxationSpec(0.65, (0.0, -1.0, 0.0), 0.2)
    static = StaticPouchSettings(100, 4, 0.0015, 0.48, 0.88, (0.0, -1.0, 0.0))
    fixed = surface_fixed_indices(len(points), patch.boundary_edges)
    spec = SurfaceTissuePipelineSpec(mode, profile, geometric, static, fixed)
    return run_surface_tissue_pipeline(points, normals, patch.faces, patch.boundary_edges, patch.weights, spec)


def _smooth_mesh(obj):
    for polygon in obj.data.polygons:
        polygon.use_smooth = True


def _add_tissue_groups(obj, geometry, patch):
    from anthroforge.core.vcp.soft_tissue_surface_inflation import backing_vertex_indices, perimeter_vertex_indices
    backing = backing_vertex_indices(geometry)
    perimeter = perimeter_vertex_indices(geometry, patch.boundary_edges)
    _weighted_group(obj, "AF_ST_BACKING", backing, (0.55,) * len(backing))
    _weighted_group(obj, "AF_ST_PERIMETER", perimeter, (1.0,) * len(perimeter))
    _weighted_group(obj, "AF_ST_THICKNESS", range(geometry.base_vertex_count), patch.weights)


def _weighted_group(obj, name, indices, weights):
    group = obj.vertex_groups.new(name=name)
    for index, weight in zip(indices, weights):
        group.add((int(index),), float(weight), "REPLACE")
    return group


def _tag_tissue(obj, name, mode, base, scp):
    model = _abdominal_model(name, mode, base, scp)
    obj["af_soft_tissue_vcp"] = True
    obj["af_soft_tissue_id"] = model.id
    obj["af_soft_tissue_model"] = json.dumps(_model_payload(model), separators=(",", ":"))
    obj["af_base_surface_name"] = base.name
    obj["af_target_scp_id"] = scp.id
    obj["af_relaxation_mode"] = mode.value


def _abdominal_model(name, mode, base, scp):
    from anthroforge.core.vcp.soft_tissue_model import BaseDomain, BaseObjectSpec, BoundaryMode, SoftTissueVCPModel, TissuePreset
    from anthroforge.core.vcp.soft_tissue_model import InflationMode, InflationSpec, MaterialSpec, RelaxationSpec, SolverSpec
    sag = 0.0 if mode.value == "NONE" else 0.65
    tissue_id = "SOFT_TISSUE_ABDOMINAL_FAT_TAUT" if mode.value == "NONE" else "SOFT_TISSUE_ABDOMINAL_FAT_SAG"
    return SoftTissueVCPModel(tissue_id, name, TissuePreset.LAYER, BoundaryMode.HOST_SEALED,
                              BaseObjectSpec(BaseDomain.SURFACE, base.name, resolution=len(base.data.vertices)),
                              InflationSpec(InflationMode.NORMAL, 0.28, field_attribute="AF_ST_THICKNESS"),
                              MaterialSpec("ADIPOSE", 0.52, 0.92),
                              RelaxationSpec(sag, (0.0, -1.0, 0.0), 0.2),
                              _abdominal_attachments(scp.id), solver=_solver_spec(SolverSpec, mode))


def _solver_spec(spec_type, mode):
    iterations = 100 if mode.value == "STATIC_PBD" else 1
    passes = 4 if mode.value == "STATIC_PBD" else 1
    return spec_type(mode, iterations, passes, 1.0e-5)


def _abdominal_attachments(scp_id):
    from anthroforge.core.vcp.soft_tissue_model import AttachmentMode, AttachmentSpec, TargetKind, TargetSurface
    target = TargetKind.SCP, scp_id, TargetSurface.SCP_GEOMETRY
    perimeter = AttachmentSpec(*target, AttachmentMode.FIXED, 1.0, "AF_ST_PERIMETER")
    backing = AttachmentSpec(*target, AttachmentMode.SOFT, 0.55, "AF_ST_BACKING")
    return perimeter, backing


def _model_payload(model):
    from anthroforge.core.vcp.soft_tissue_model import model_to_dict, validate_model
    errors = validate_model(model)
    if errors:
        raise RuntimeError("; ".join(errors))
    return model_to_dict(model)


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


def create_wire(host, collection, value):
    wire = host.copy()
    wire.data = host.data.copy()
    wire.name = "AF_ABDOMEN_HOST_WIRE"
    collection.objects.link(wire)
    wire.data.materials.clear()
    wire.data.materials.append(value)
    modifier = wire.modifiers.new("AF_HOST_WIREFRAME", "WIREFRAME")
    modifier.thickness, modifier.use_replace = 0.004, True
    wire["af_soft_tissue_host_wire"] = True
    return wire


def assign_host_material(host, value):
    host.data.materials.clear()
    host.data.materials.append(value)
    _smooth_mesh(host)


def make_camera():
    data = bpy.data.cameras.new("AF_ABDOMEN_CAMERA")
    data.type, data.ortho_scale = "ORTHO", 4.25
    camera = bpy.data.objects.new("AF_ABDOMEN_CAMERA", data)
    bpy.context.scene.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    return camera


def point_at(obj, target=(0.0, -0.1, 0.12)):
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
    scene.render.resolution_x = scene.render.resolution_y = 768
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    if scene.world is None:
        scene.world = bpy.data.worlds.new("AF_ABDOMEN_WORLD")
    scene.world.color = (0.008, 0.012, 0.02)
    add_light("AF_ABDOMEN_KEY", (-3.5, -3.0, 5.5), 1100.0, 3.5)
    add_light("AF_ABDOMEN_FILL", (3.0, 2.2, 4.0), 750.0, 3.0)


def _set_eevee(scene):
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            return
        except TypeError:
            continue


def render_variant(camera, path, location, tissues, visible=None, base=None):
    for obj in tissues:
        obj.hide_render = obj != visible
    if base is not None:
        base.hide_render = visible is not None
    camera.location = location
    point_at(camera)
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def render_experiment(folder, camera, tissues, base):
    folder.mkdir(parents=True, exist_ok=True)
    taut, sag = tissues
    render_variant(camera, folder / "abdominal_fat_taut_front.png", (0.0, 0.0, 5.0), tissues, taut, base)
    render_variant(camera, folder / "abdominal_fat_sag_front.png", (0.0, 0.0, 5.0), tissues, sag, base)
    render_variant(camera, folder / "abdominal_fat_taut_side.png", (5.0, 0.0, 0.2), tissues, taut, base)
    render_variant(camera, folder / "abdominal_fat_sag_side.png", (5.0, 0.0, 0.2), tissues, sag, base)
    render_variant(camera, folder / "abdominal_fat_sag_three_quarter.png", (3.8, -4.5, 4.2), tissues, sag, base)
    render_variant(camera, folder / "abdominal_fat_attachment_debug.png", (0.0, 0.0, 5.0), tissues, None, base)
    _restore_visibility(taut, sag, base)


def _restore_visibility(taut, sag, base):
    taut.hide_render, taut.hide_viewport = True, True
    sag.hide_render, sag.hide_viewport = False, False
    base.hide_render, base.hide_viewport = True, True


def build_experiment(args):
    from anthroforge.core.vcp.soft_tissue_model import SolverMode
    collection = make_collection("AF_SOFT_TISSUE_ABDOMEN_EXPERIMENT")
    debug = make_collection("AF_SOFT_TISSUE_ABDOMEN_DEBUG")
    root, scp, host = create_host(collection)
    signature_before = _host_signature(host)
    patch = patch_geometry(args.rings, args.segments)
    bindings = capture_bindings(root, scp, patch)
    deform_host(host)
    points, normals = resolve_bindings(root, scp, bindings)
    mode = SolverMode(args.relaxation_mode)
    visuals = _create_fat_visuals(patch, points, normals, bindings, scp, collection, debug, mode)
    return root, scp, host, signature_before, patch, bindings, visuals


def _create_fat_visuals(patch, points, normals, bindings, scp, collection, debug, mode):
    base_mat = material("AF_ABDOMEN_BASE_MAT", (0.04, 0.82, 1.0), roughness=0.3, emission=2.2)
    fat_mat = material("AF_ABDOMINAL_FAT_MAT", (0.82, 0.35, 0.075), roughness=0.52)
    base = make_base_patch(patch, points, bindings, debug, base_mat)
    from anthroforge.core.vcp.soft_tissue_model import SolverMode
    taut = create_tissue("AF_SOFT_TISSUE_ABDOMEN_TAUT", SolverMode.NONE, base, patch, points,
                         normals, scp, collection, fat_mat)
    sag = create_tissue("AF_SOFT_TISSUE_ABDOMEN_SAG", mode, base, patch, points,
                        normals, scp, collection, fat_mat)
    return base, taut, sag


def _host_signature(host):
    from anthroforge.core.scp_proxy.signature import topology_signature
    return topology_signature(bpy.context.scene, host)


def metrics_payload(scp, host, before, patch, bindings, taut, sag):
    taut_obj, taut_result = taut
    sag_obj, sag_result = sag
    drop = _front_centroid_y(taut_result) - _front_centroid_y(sag_result)
    return {"host_scp_id": scp.id, "host_object": host.name,
            "topology_preserved": before == _host_signature(host),
            "base_vertices": len(patch.points), "base_faces": len(patch.faces),
            "surface_binding_count": len(bindings), "thickness_min": min(sag_result.rest.thicknesses),
            "thickness_max": max(sag_result.rest.thicknesses), "sag_centroid_drop": drop,
            "relaxation_mode": sag_result.mode.value,
            "soft_tissue_objects": [taut_obj.name, sag_obj.name]}


def _front_centroid_y(result):
    points = result.final_vertices[:result.rest.base_vertex_count]
    return sum(point[1] for point in points) / len(points)


def finish(args, data):
    root, scp, host, before, patch, bindings, visuals = data
    base, taut, sag = visuals
    host_mat = material("AF_ABDOMEN_HOST_MAT", (0.27, 0.33, 0.42), metallic=0.04, roughness=0.78)
    wire_mat = material("AF_ABDOMEN_WIRE_MAT", (0.03, 0.05, 0.085), roughness=0.8)
    assign_host_material(host, host_mat)
    create_wire(host, next(iter(host.users_collection)), wire_mat)
    configure_render()
    render_experiment(Path(args.render_dir).resolve(), make_camera(), (taut[0], sag[0]), base)
    metrics = metrics_payload(scp, host, before, patch, bindings, taut, sag)
    _save_artifacts(args, root, metrics)
    print("AF_SOFT_TISSUE_ABDOMEN_PROTOTYPE", json.dumps(metrics, sort_keys=True), flush=True)


def _save_artifacts(args, root, metrics):
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    root["af_soft_tissue_abdomen_experiment"] = json.dumps(metrics, separators=(",", ":"))
    (Path(args.render_dir).resolve() / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=str(output), copy=True)


def main():
    args = parse_args()
    reset_and_register()
    finish(args, build_experiment(args))


if __name__ == "__main__":
    main()

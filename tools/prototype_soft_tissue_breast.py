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
class RootPatch:
    side: str
    points: tuple
    faces: tuple
    boundary_edges: tuple
    weights: tuple
    rings: int
    segments: int


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--rings", type=int, default=7)
    parser.add_argument("--segments", type=int, default=36)
    parser.add_argument("--relaxation-mode", choices=("NONE", "GEOMETRIC", "STATIC_PBD"),
                        default="STATIC_PBD")
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


def grid_geometry(columns=21, rows=19, half_width=1.8, half_height=1.6):
    vertices = tuple(_grid_point(x, z, columns, rows, half_width, half_height)
                     for z in range(rows) for x in range(columns))
    faces = tuple(_grid_face(x, z, columns) for z in range(rows - 1) for x in range(columns - 1))
    return vertices, faces


def _grid_point(x, z, columns, rows, half_width, half_height):
    px = -half_width + 2.0 * half_width * x / (columns - 1)
    pz = -half_height + 2.0 * half_height * z / (rows - 1)
    return px, 0.0, pz


def _grid_face(x, z, columns):
    first = z * columns + x
    return first, first + 1, first + columns + 1, first + columns


def create_host(collection):
    from anthroforge.core.scp_runtime.object_roles import create_scp, set_scp_geometry_object, set_scp_transform_object
    from anthroforge.core.utils import ensure_af_root
    host = make_mesh_object("AF_THORAX_HOST_SCP", *grid_geometry(), collection)
    root = ensure_af_root(bpy.context.scene)
    scp = create_scp(root, "Anterior Thorax Host")
    set_scp_transform_object(root, scp, host)
    set_scp_geometry_object(root, scp, host)
    host["af_soft_tissue_host"] = True
    return root, scp, host


def root_patch(side, rings, segments):
    rings, segments = max(2, int(rings)), max(12, int(segments))
    center = -0.67 if side == "LEFT" else 0.67
    rows = tuple(_patch_ring(center, ring, rings, segments) for ring in range(1, rings + 1))
    points = ((center, 0.0, 0.05),) + tuple(point for row in rows for point in row)
    weights = (1.0,) + tuple(_patch_weight(ring, rings, index, segments)
                             for ring in range(1, rings + 1) for index in range(segments))
    faces = _center_faces(segments) + _ring_faces(rings, segments)
    return RootPatch(side, points, faces, _outer_boundary(rings, segments), weights, rings, segments)


def _patch_ring(center, ring, rings, segments):
    radius = ring / rings
    return tuple(_patch_point(center, radius, 2.0 * math.pi * index / segments)
                 for index in range(segments))


def _patch_point(center, radius, angle):
    x = center + 0.62 * radius * math.cos(angle)
    z = 0.05 + 0.68 * radius * math.sin(angle)
    return x, 0.0, z


def _patch_weight(ring, rings, index, segments):
    radius = ring / rings
    angle = 2.0 * math.pi * index / segments
    envelope = max(0.0, math.cos(0.5 * math.pi * radius)) ** 0.88
    lower_fullness = 1.0 + 0.16 * max(0.0, -math.sin(angle)) * (1.0 - radius)
    return min(1.0, envelope * lower_fullness)


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
        raise RuntimeError(f"Could not bind {patch.side} breast root to {scp.id}.")
    return values


def deform_host(host):
    for vertex in host.data.vertices:
        x, z = float(vertex.co.x), float(vertex.co.z)
        barrel = -0.17 + 0.28 * (x / 1.8) ** 2
        vertical = 0.045 * (z / 1.6) ** 2
        sternum = -0.045 * math.exp(-(x / 0.28) ** 2)
        vertex.co.y = barrel + vertical + sternum
    host.data.update()
    bpy.context.view_layer.update()


def resolve_bindings(root, scp, bindings):
    from anthroforge.core.vcp.attachment_backend import attachment_runtime, resolve_attachment_normal, resolve_attachment_world
    runtime = attachment_runtime(bpy.context.scene)
    points = tuple(resolve_attachment_world(root, bpy.context.scene, scp.id, raw, runtime) for raw in bindings)
    normals = tuple(resolve_attachment_normal(root, bpy.context.scene, scp.id, raw, runtime) for raw in bindings)
    if any(value is None for value in points + normals):
        raise RuntimeError(f"A breast root binding no longer resolves on {scp.id}.")
    return tuple(tuple(point) for point in points), tuple(tuple(normal) for normal in normals)


def make_base_patch(patch, points, bindings, collection, value):
    name = f"AF_BREAST_{patch.side}_BASE_SURFACE"
    obj = make_mesh_object(name, points, patch.faces, collection)
    obj.data.materials.append(value)
    obj["af_soft_tissue_base"] = True
    obj["af_surface_bindings"] = _binding_json(bindings)
    _weighted_group(obj, "AF_ST_INFLATION", range(len(points)), patch.weights)
    modifier = obj.modifiers.new("AF_BASE_WIREFRAME", "WIREFRAME")
    modifier.thickness, modifier.use_replace = 0.007, True
    return obj


def _binding_json(bindings):
    return json.dumps([json.loads(raw) for raw in bindings], separators=(",", ":"))


def run_breast_pipeline(patch, points, normals, mode):
    from anthroforge.core.vcp.soft_tissue_static_pouch import StaticPouchSettings
    from anthroforge.core.vcp.soft_tissue_surface_inflation import SurfaceLayerProfile
    from anthroforge.core.vcp.soft_tissue_surface_pipeline import GeometricRelaxationSpec
    from anthroforge.core.vcp.soft_tissue_surface_pipeline import SurfaceTissuePipelineSpec, run_surface_tissue_pipeline
    from anthroforge.core.vcp.soft_tissue_surface_pipeline import surface_fixed_indices
    profile = SurfaceLayerProfile(0.62, 0.012, 0.58)
    fixed = surface_fixed_indices(len(points), patch.boundary_edges)
    tethers = pouch_tethers(patch, points, profile)
    geometric = GeometricRelaxationSpec(0.58, (0.0, 0.0, -1.0), 0.3)
    static = StaticPouchSettings(110, 4, 0.0015, 0.48, 0.88, (0.0, 0.0, -1.0))
    spec = SurfaceTissuePipelineSpec(mode, profile, geometric, static, fixed, tethers)
    result = run_surface_tissue_pipeline(points, normals, patch.faces, patch.boundary_edges, patch.weights, spec)
    return result, fixed, tethers


def pouch_tethers(patch, points, profile):
    from anthroforge.core.vcp.soft_tissue_static_pouch import StaticTether
    from anthroforge.core.vcp.soft_tissue_surface_inflation import surface_thickness
    ring = max(2, round(patch.rings * 0.55))
    step = max(1, patch.segments // 8)
    indices = tuple(1 + (ring - 1) * patch.segments + index for index in range(0, patch.segments, step))
    return tuple(StaticTether(index, points[index], surface_thickness(patch.weights[index], profile), 0.015)
                 for index in indices)


def create_tissue(name, vertices, geometry, collection, value):
    obj = make_mesh_object(name, vertices, geometry.faces, collection)
    obj.data.materials.append(value)
    _smooth_mesh(obj)
    modifier = obj.modifiers.new("AF_TISSUE_SMOOTH", "SUBSURF")
    modifier.levels = modifier.render_levels = 1
    return obj


def _smooth_mesh(obj):
    for polygon in obj.data.polygons:
        polygon.use_smooth = True


def add_tissue_groups(obj, patch, geometry, fixed, tethers):
    from anthroforge.core.vcp.soft_tissue_surface_inflation import backing_vertex_indices, perimeter_vertex_indices
    backing = backing_vertex_indices(geometry)
    perimeter = perimeter_vertex_indices(geometry, patch.boundary_edges)
    tether_indices = tuple(tether.vertex_index for tether in tethers)
    _weighted_group(obj, "AF_ST_BACKING", backing, (0.7,) * len(backing))
    _weighted_group(obj, "AF_ST_ROOT", perimeter, (1.0,) * len(perimeter))
    _weighted_group(obj, "AF_ST_SUSPENSORY", tether_indices, (1.0,) * len(tether_indices))
    _weighted_group(obj, "AF_ST_INFLATION", range(geometry.base_vertex_count), patch.weights)


def _weighted_group(obj, name, indices, weights):
    group = obj.vertex_groups.new(name=name)
    for index, weight in zip(indices, weights):
        group.add((int(index),), float(weight), "REPLACE")
    return group


def tag_final_tissue(obj, patch, base, scp, mode):
    model = _breast_model(patch, base, scp, mode)
    obj["af_soft_tissue_vcp"] = True
    obj["af_soft_tissue_id"] = model.id
    obj["af_soft_tissue_model"] = json.dumps(_model_payload(model), separators=(",", ":"))
    obj["af_base_surface_name"] = base.name
    obj["af_target_scp_id"] = scp.id
    obj["af_relaxation_mode"] = mode.value


def _breast_model(patch, base, scp, mode):
    from anthroforge.core.vcp.soft_tissue_model import BaseDomain, BaseObjectSpec, BoundaryMode, SoftTissueVCPModel, TissuePreset
    from anthroforge.core.vcp.soft_tissue_model import InflationMode, InflationSpec, MaterialSpec, RelaxationSpec, SolverSpec
    tissue_id = f"SOFT_TISSUE_BREAST_{patch.side}"
    sag = 0.0 if mode.value == "NONE" else 0.58
    return SoftTissueVCPModel(tissue_id, f"{patch.side.title()} Breast", TissuePreset.POUCH,
                              BoundaryMode.HOST_SEALED, BaseObjectSpec(BaseDomain.SURFACE, base.name,
                              resolution=len(base.data.vertices)), InflationSpec(InflationMode.NORMAL, 0.62,
                              field_attribute="AF_ST_INFLATION"), MaterialSpec("BREAST", 0.62, 0.98),
                              RelaxationSpec(sag, (0.0, 0.0, -1.0), 0.3),
                              _breast_attachments(scp.id), solver=_solver_spec(SolverSpec, mode))


def _solver_spec(spec_type, mode):
    iterations = 110 if mode.value == "STATIC_PBD" else 1
    passes = 4 if mode.value == "STATIC_PBD" else 1
    return spec_type(mode, iterations, passes, 1.0e-5)


def _breast_attachments(scp_id):
    from anthroforge.core.vcp.soft_tissue_model import AttachmentMode, AttachmentSpec, TargetKind, TargetSurface
    target = TargetKind.SCP, scp_id, TargetSurface.SCP_GEOMETRY
    root = AttachmentSpec(*target, AttachmentMode.FIXED, 1.0, "AF_ST_ROOT")
    backing = AttachmentSpec(*target, AttachmentMode.SOFT, 0.7, "AF_ST_BACKING")
    suspension = AttachmentSpec(*target, AttachmentMode.SOFT, 0.4, "AF_ST_SUSPENSORY")
    return root, backing, suspension


def _model_payload(model):
    from anthroforge.core.vcp.soft_tissue_model import model_to_dict, validate_model
    errors = validate_model(model)
    if errors:
        raise RuntimeError("; ".join(errors))
    return model_to_dict(model)


def make_tether_visual(name, solved, tethers, collection, value):
    data = bpy.data.curves.new(f"{name}_CURVE", "CURVE")
    data.dimensions, data.bevel_depth, data.bevel_resolution = "3D", 0.008, 2
    for tether in tethers:
        spline = data.splines.new("POLY")
        spline.points.add(1)
        spline.points[0].co = (*tether.anchor, 1.0)
        spline.points[1].co = (*solved[tether.vertex_index], 1.0)
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    data.materials.append(value)
    obj["af_soft_tissue_tethers"] = True
    return obj


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
    wire.name = "AF_THORAX_HOST_WIRE"
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
    data = bpy.data.cameras.new("AF_BREAST_CAMERA")
    data.type, data.ortho_scale = "ORTHO", 4.15
    camera = bpy.data.objects.new("AF_BREAST_CAMERA", data)
    bpy.context.scene.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    return camera


def point_at(obj, target=(0.0, -0.15, 0.0)):
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
        scene.world = bpy.data.worlds.new("AF_BREAST_WORLD")
    scene.world.color = (0.008, 0.012, 0.02)
    add_light("AF_BREAST_KEY", (-3.2, -4.5, 4.5), 1100.0, 3.2)
    add_light("AF_BREAST_FILL", (3.0, -2.8, 2.2), 700.0, 2.8)


def _set_eevee(scene):
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            return
        except TypeError:
            continue


def render_variant(camera, path, location, all_tissues, visible, debug_objects=(), show_debug=False):
    for obj in all_tissues:
        obj.hide_render = obj not in visible
    for obj in debug_objects:
        obj.hide_render = not show_debug
    camera.location = location
    point_at(camera)
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def render_experiment(folder, camera, rest, final, debug):
    folder.mkdir(parents=True, exist_ok=True)
    all_tissues = rest + final
    render_variant(camera, folder / "breast_rest_front.png", (0.0, -6.0, 0.0), all_tissues, rest, debug)
    render_variant(camera, folder / "breast_gravity_front.png", (0.0, -6.0, 0.0), all_tissues, final, debug)
    render_variant(camera, folder / "breast_gravity_three_quarter.png", (3.8, -5.8, 2.2), all_tissues, final, debug)
    render_variant(camera, folder / "breast_gravity_profile.png", (5.8, -0.4, 0.2), all_tissues, final, debug)
    render_variant(camera, folder / "breast_attachment_debug.png", (0.0, -6.0, 0.0), all_tissues, (), debug, True)
    render_variant(camera, folder / "breast_attachment_debug_three_quarter.png", (3.8, -5.8, 2.2), all_tissues, (), debug, True)
    _restore_visibility(rest, final, debug)


def _restore_visibility(rest, final, debug):
    for obj in rest + debug:
        obj.hide_render, obj.hide_viewport = True, True
    for obj in final:
        obj.hide_render, obj.hide_viewport = False, False


def build_experiment(args):
    from anthroforge.core.vcp.soft_tissue_model import SolverMode
    collection = make_collection("AF_SOFT_TISSUE_BREAST_EXPERIMENT")
    debug = make_collection("AF_SOFT_TISSUE_BREAST_DEBUG")
    root, scp, host = create_host(collection)
    signature_before = _host_signature(host)
    patches = tuple(root_patch(side, args.rings, args.segments) for side in ("LEFT", "RIGHT"))
    bindings = tuple(capture_bindings(root, scp, patch) for patch in patches)
    deform_host(host)
    resolved = tuple(resolve_bindings(root, scp, raw) for raw in bindings)
    mode = SolverMode(args.relaxation_mode)
    visuals = _create_breasts(patches, resolved, bindings, scp, collection, debug, mode)
    return root, scp, host, signature_before, patches, bindings, visuals


def _create_breasts(patches, resolved, bindings, scp, collection, debug, mode):
    mats = _experiment_materials()
    bases = tuple(make_base_patch(patch, points, raw, debug, mats["base"])
                  for patch, (points, _), raw in zip(patches, resolved, bindings))
    rows = tuple(_create_breast(patch, points, normals, base, scp, collection, debug, mats, mode)
                 for patch, (points, normals), base in zip(patches, resolved, bases))
    rest, final, tethers, data = zip(*rows)
    return bases, tuple(rest), tuple(final), tuple(tethers), tuple(data)


def _create_breast(patch, points, normals, base, scp, collection, debug, mats, mode):
    result, fixed, tethers = run_breast_pipeline(patch, points, normals, mode)
    geometry, solved = result.rest, result.final_vertices
    rest = create_tissue(f"AF_BREAST_{patch.side}_REST", geometry.vertices, geometry, debug, mats["rest"])
    final = create_tissue(f"AF_SOFT_TISSUE_BREAST_{patch.side}", solved, geometry, collection, mats["final"])
    add_tissue_groups(final, patch, geometry, fixed, tethers)
    tag_final_tissue(final, patch, base, scp, result.mode)
    visual = make_tether_visual(f"AF_BREAST_{patch.side}_TETHERS", solved, tethers, debug, mats["tether"])
    return rest, final, visual, (geometry, solved, fixed, tethers, result.mode)


def _experiment_materials():
    return {"base": material("AF_BREAST_BASE_MAT", (0.03, 0.82, 1.0), roughness=0.3, emission=2.2),
            "tether": material("AF_BREAST_TETHER_MAT", (0.12, 1.0, 0.28), roughness=0.25, emission=2.0),
            "rest": material("AF_BREAST_REST_MAT", (0.42, 0.32, 0.72), roughness=0.48),
            "final": material("AF_BREAST_FINAL_MAT", (0.82, 0.24, 0.34), roughness=0.48)}


def _host_signature(host):
    from anthroforge.core.scp_proxy.signature import topology_signature
    return topology_signature(bpy.context.scene, host)


def metrics_payload(scp, host, before, patches, bindings, data):
    rows = [_breast_metrics(patch, geometry, solved, tethers, mode)
            for patch, (geometry, solved, _fixed, tethers, mode) in zip(patches, data)]
    return {"host_scp_id": scp.id, "host_object": host.name,
            "topology_preserved": before == _host_signature(host),
            "relaxation_mode": data[0][4].value,
            "surface_binding_count": sum(len(raw) for raw in bindings), "breasts": rows}


def _breast_metrics(patch, geometry, solved, tethers, mode):
    from anthroforge.core.vcp.soft_tissue_static_pouch import mesh_volume, triangulate_faces
    triangles = triangulate_faces(geometry.faces)
    rest = abs(mesh_volume(geometry.vertices, triangles))
    final = abs(mesh_volume(solved, triangles))
    drop = _centroid_z(geometry.vertices, geometry.base_vertex_count) - _centroid_z(solved, geometry.base_vertex_count)
    return {"side": patch.side, "base_vertices": len(patch.points), "tethers": len(tethers),
            "relaxation_mode": mode.value,
            "rest_volume": rest, "final_volume": final, "relative_volume_error": abs(final - rest) / rest,
            "front_centroid_drop": drop}


def _centroid_z(vertices, count):
    return sum(vertices[index][2] for index in range(count)) / count


def finish(args, data):
    root, scp, host, before, patches, bindings, visuals = data
    bases, rest, final, tethers, solve_data = visuals
    host_mat = material("AF_THORAX_HOST_MAT", (0.27, 0.33, 0.42), metallic=0.04, roughness=0.78)
    wire_mat = material("AF_THORAX_WIRE_MAT", (0.03, 0.05, 0.085), roughness=0.8)
    assign_host_material(host, host_mat)
    create_wire(host, next(iter(host.users_collection)), wire_mat)
    configure_render()
    render_experiment(Path(args.render_dir).resolve(), make_camera(), rest, final, bases + tethers)
    metrics = metrics_payload(scp, host, before, patches, bindings, solve_data)
    _save_artifacts(args, root, metrics)
    print("AF_SOFT_TISSUE_BREAST_PROTOTYPE", json.dumps(metrics, sort_keys=True), flush=True)


def _save_artifacts(args, root, metrics):
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    root["af_soft_tissue_breast_experiment"] = json.dumps(metrics, separators=(",", ":"))
    (Path(args.render_dir).resolve() / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=str(output), copy=True)


def main():
    args = parse_args()
    reset_and_register()
    finish(args, build_experiment(args))


if __name__ == "__main__":
    main()

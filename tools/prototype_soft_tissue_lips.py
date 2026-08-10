import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector


ADDON_ROOT = Path(__file__).resolve().parents[1]
if str(ADDON_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT.parent))


@dataclass(frozen=True)
class LipInput:
    tissue_id: str
    name: str
    points: tuple
    half_width: float
    depth: float
    sag_fraction: float


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--samples", type=int, default=33)
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


def grid_geometry(columns=13, rows=9, half_width=1.35, half_height=0.78):
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
    host = make_mesh_object("AF_LIP_HOST_PLANE", *grid_geometry(), collection)
    root = ensure_af_root(bpy.context.scene)
    scp = create_scp(root, "Lip Host Plane")
    set_scp_transform_object(root, scp, host)
    set_scp_geometry_object(root, scp, host)
    host["af_soft_tissue_host"] = True
    return root, scp, host


def lip_inputs(samples):
    values = tuple(-1.0 + 2.0 * index / (samples - 1) for index in range(samples))
    upper = tuple((0.92 * value, _upper_height(value), 0.0) for value in values)
    lower = tuple((0.92 * value, _lower_height(value), 0.0) for value in values)
    return (LipInput("SOFT_TISSUE_LIP_UPPER", "Upper Lip", upper, 0.09, 0.135, 0.035),
            LipInput("SOFT_TISSUE_LIP_LOWER", "Lower Lip", lower, 0.105, 0.15, 0.08))


def _upper_height(value):
    envelope = max(0.0, 1.0 - value * value)
    return envelope * (0.105 + 0.16 * abs(value))


def _lower_height(value):
    envelope = max(0.0, 1.0 - value * value)
    return -envelope * (0.16 - 0.025 * abs(value))


def capture_bindings(root, scp, inputs):
    from anthroforge.core.vcp.attachment_backend import attachment_runtime, capture_attachment_from_world
    runtime = attachment_runtime(bpy.context.scene)
    bindings = tuple(capture_attachment_from_world(root, bpy.context.scene, scp.id, Vector(point), runtime)
                     for point in inputs.points)
    if any(value is None for value in bindings):
        raise RuntimeError(f"Could not bind {inputs.name} to {scp.id}.")
    return bindings


def deform_host(host):
    for vertex in host.data.vertices:
        x, y = float(vertex.co.x), float(vertex.co.y)
        vertex.co.z = 0.105 * (1.0 - 0.28 * (x / 1.35) ** 2) * (1.0 - 0.18 * (y / 0.78) ** 2)
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


def make_curve(name, points, collection, material, bindings):
    data = bpy.data.curves.new(f"{name}_CURVE", "CURVE")
    data.dimensions, data.resolution_u, data.bevel_depth = "3D", 2, 0.008
    spline = data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for item, point in zip(spline.points, points):
        item.co = (*point, 1.0)
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    data.materials.append(material)
    obj["af_soft_tissue_base"] = True
    obj["af_surface_bindings"] = _binding_json(bindings)
    return obj


def _binding_json(bindings):
    return json.dumps([json.loads(raw) for raw in bindings], separators=(",", ":"))


def create_tissue(inputs, curve, points, normals, scp, collection, material):
    from anthroforge.core.vcp.soft_tissue_curve_inflation import CurveRidgeMesh, CurveRidgeProfile
    from anthroforge.core.vcp.soft_tissue_curve_inflation import backing_vertex_indices, commissure_vertex_indices
    from anthroforge.core.vcp.soft_tissue_curve_inflation import geometric_curve_relaxation, inflate_curve_ridge
    profile = CurveRidgeProfile(inputs.half_width, inputs.depth, 0.62, 11, 0.12)
    rest = inflate_curve_ridge(points, normals, profile)
    fixed = backing_vertex_indices(rest) + commissure_vertex_indices(rest)
    vertices = geometric_curve_relaxation(rest, inputs.sag_fraction, (0.0, -1.0, 0.0), fixed,
                                          inputs.depth * 0.2, inputs.depth)
    geometry = CurveRidgeMesh(vertices, rest.faces, rest.ring_size)
    obj = make_mesh_object(f"AF_{inputs.tissue_id}", geometry.vertices, geometry.faces, collection)
    obj.data.materials.append(material)
    _smooth_mesh(obj)
    _add_attachment_groups(obj, geometry)
    _tag_tissue(obj, inputs, curve, scp, geometry)
    return obj, geometry


def _smooth_mesh(obj):
    for polygon in obj.data.polygons:
        polygon.use_smooth = True


def _add_attachment_groups(obj, geometry):
    from anthroforge.core.vcp.soft_tissue_curve_inflation import backing_vertex_indices, commissure_vertex_indices
    backing = obj.vertex_groups.new(name="AF_ST_BACKING")
    backing.add(backing_vertex_indices(geometry), 1.0, "REPLACE")
    commissures = obj.vertex_groups.new(name="AF_ST_COMMISSURES")
    commissures.add(commissure_vertex_indices(geometry), 1.0, "REPLACE")


def _tag_tissue(obj, inputs, curve, scp, geometry):
    model = _lip_model(inputs, curve, scp)
    obj["af_soft_tissue_vcp"] = True
    obj["af_soft_tissue_id"] = inputs.tissue_id
    obj["af_soft_tissue_model"] = json.dumps(_model_payload(model), separators=(",", ":"))
    obj["af_base_curve_name"] = curve.name
    obj["af_target_scp_id"] = scp.id
    obj["af_profile_ring_size"] = geometry.ring_size


def _lip_model(inputs, curve, scp):
    from anthroforge.core.vcp.soft_tissue_model import BaseDomain, BaseObjectSpec, BoundaryMode, SoftTissueVCPModel, TissuePreset
    from anthroforge.core.vcp.soft_tissue_model import InflationMode, InflationSpec, MaterialSpec, RelaxationSpec, SolverMode, SolverSpec
    attachments = _lip_attachments(scp.id)
    return SoftTissueVCPModel(inputs.tissue_id, inputs.name, TissuePreset.RIM, BoundaryMode.HOST_SEALED,
                              BaseObjectSpec(BaseDomain.CURVE, curve.name, resolution=len(inputs.points)),
                              InflationSpec(InflationMode.PROFILE, inputs.depth, profile_width=inputs.half_width,
                                            profile_power=0.62, profile_segments=11, endpoint_taper=0.12),
                              MaterialSpec("LIP", 0.72, 0.92),
                              RelaxationSpec(inputs.sag_fraction, (0.0, -1.0, 0.0), inputs.depth * 0.2),
                              attachments, solver=SolverSpec(SolverMode.GEOMETRIC, 1, 1, 1.0e-5))


def _lip_attachments(scp_id):
    from anthroforge.core.vcp.soft_tissue_model import AttachmentMode, AttachmentSpec, TargetKind, TargetSurface
    target = TargetKind.SCP, scp_id, TargetSurface.SCP_GEOMETRY
    backing = AttachmentSpec(*target, AttachmentMode.FIXED, 1.0, "AF_ST_BACKING")
    corners = AttachmentSpec(*target, AttachmentMode.FIXED, 1.0, "AF_ST_COMMISSURES")
    return backing, corners


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
    wire.name = "AF_LIP_HOST_WIRE"
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
    data = bpy.data.cameras.new("AF_LIP_CAMERA")
    data.type, data.ortho_scale = "ORTHO", 3.05
    camera = bpy.data.objects.new("AF_LIP_CAMERA", data)
    bpy.context.scene.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    return camera


def point_at(obj, target=(0.0, 0.0, 0.08)):
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
        scene.world = bpy.data.worlds.new("AF_LIP_WORLD")
    scene.world.color = (0.008, 0.012, 0.02)
    add_light("AF_LIP_KEY", (-2.8, -3.0, 4.5), 900.0, 3.0)
    add_light("AF_LIP_FILL", (2.4, 1.8, 3.2), 650.0, 2.5)


def _set_eevee(scene):
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            return
        except TypeError:
            continue


def render_view(camera, path, location, tissues, curves, debug=False):
    for obj in tissues:
        obj.hide_render = debug
    for obj in curves:
        obj.hide_render = not debug
    camera.location = location
    point_at(camera)
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def render_experiment(folder, camera, tissues, curves):
    folder.mkdir(parents=True, exist_ok=True)
    render_view(camera, folder / "lips_front.png", (0.0, 0.0, 4.0), tissues, curves)
    render_view(camera, folder / "lips_three_quarter.png", (2.7, -3.2, 3.2), tissues, curves)
    render_view(camera, folder / "lips_attachment_debug.png", (0.0, 0.0, 4.0), tissues, curves, True)
    for obj in tissues:
        obj.hide_render = False
    for obj in curves:
        obj.hide_render = True


def build_experiment(args):
    collection = make_collection("AF_SOFT_TISSUE_LIP_EXPERIMENT")
    debug = make_collection("AF_SOFT_TISSUE_LIP_DEBUG")
    root, scp, host = create_host(collection)
    signature_before = _host_signature(host)
    source = lip_inputs(max(5, int(args.samples)))
    bindings = tuple(capture_bindings(root, scp, item) for item in source)
    deform_host(host)
    resolved = tuple(resolve_bindings(root, scp, item) for item in bindings)
    visuals = _create_lips(source, resolved, bindings, scp, collection, debug)
    return root, scp, host, signature_before, source, bindings, visuals


def _create_lips(source, resolved, bindings, scp, collection, debug):
    curve_mat = material("AF_LIP_BASE_MAT", (0.05, 0.8, 1.0), roughness=0.3, emission=2.5)
    tissue_mats = (material("AF_UPPER_LIP_MAT", (0.72, 0.055, 0.12), roughness=0.38),
                   material("AF_LOWER_LIP_MAT", (0.8, 0.075, 0.15), roughness=0.42))
    curves = tuple(make_curve(f"AF_{item.tissue_id}_BASE", points, debug, curve_mat, raw)
                   for item, (points, _), raw in zip(source, resolved, bindings))
    tissues = tuple(create_tissue(item, curve, points, normals, scp, collection, mat)[0]
                    for item, curve, (points, normals), mat in zip(source, curves, resolved, tissue_mats))
    return curves, tissues


def _host_signature(host):
    from anthroforge.core.scp_proxy.signature import topology_signature
    return topology_signature(bpy.context.scene, host)


def metrics_payload(scp, host, before, source, bindings, tissues):
    after = _host_signature(host)
    return {"host_scp_id": scp.id, "host_object": host.name, "topology_preserved": before == after,
            "host_topology_signature": after, "lip_count": len(tissues),
            "base_curve_samples": {item.tissue_id: len(item.points) for item in source},
            "surface_binding_count": sum(len(item) for item in bindings),
            "soft_tissue_objects": [obj.name for obj in tissues]}


def finish(args, data):
    root, scp, host, before, source, bindings, visuals = data
    curves, tissues = visuals
    host_mat = material("AF_LIP_HOST_MAT", (0.28, 0.34, 0.43), metallic=0.05, roughness=0.75)
    wire_mat = material("AF_LIP_WIRE_MAT", (0.035, 0.055, 0.09), roughness=0.8)
    assign_host_material(host, host_mat)
    create_wire(host, next(iter(host.users_collection)), wire_mat)
    configure_render()
    camera = make_camera()
    render_experiment(Path(args.render_dir).resolve(), camera, tissues, curves)
    metrics = metrics_payload(scp, host, before, source, bindings, tissues)
    _save_artifacts(args, root, metrics)
    print("AF_SOFT_TISSUE_LIP_PROTOTYPE", json.dumps(metrics, sort_keys=True), flush=True)


def _save_artifacts(args, root, metrics):
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    root["af_soft_tissue_lip_experiment"] = json.dumps(metrics, separators=(",", ":"))
    (Path(args.render_dir).resolve() / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=str(output), copy=True)


def main():
    args = parse_args()
    reset_and_register()
    finish(args, build_experiment(args))


if __name__ == "__main__":
    main()

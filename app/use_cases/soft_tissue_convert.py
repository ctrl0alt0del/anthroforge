import bpy
from mathutils import Vector

from ..queries.root import root_for_context
from ..queries.vcp import active_blob_from_context, blob_proxy_for_context, soft_tissue_proxy_for_context
from .results import failure, success
from ...core.id_utils import next_prefixed_id
from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates
from ...core.vcp.runtime_state import soft_tissue_status
from ...core.vcp.soft_tissue_closed_bulk import LegacyBlobSpec, closed_bulk_model_from_legacy
from ...core.vcp.soft_tissue_model import AttachmentSpec, TargetKind, TargetSurface
from ...core.vcp.soft_tissue_static_pouch import mesh_volume, triangulate_faces


def convert_blob_to_soft_tissue(context):
    root = root_for_context(context)
    blob = active_blob_from_context(context)
    blob_id = "" if blob is None else str(blob.id)
    error = _preflight(blob)
    if error:
        return failure(error)
    old = _legacy_geometry(context, blob)
    if old is None:
        return failure("Blob proxy is missing; recompute it before conversion.")
    tissue, point = _create_candidate(root, context.scene, blob)
    result = _attempt_conversion(context, root, blob, blob_id, tissue, point, old)
    return result


def _attempt_conversion(context, root, blob, blob_id, tissue, point, old):
    try:
        _sync_candidate(root, context.scene, tissue.id)
        _validate_candidate(context, tissue, old)
        _commit_candidate(root, context.scene, blob, tissue)
    except Exception as exc:
        _rollback_candidate(root, context.scene, tissue, point)
        return failure(f"Blob conversion rolled back: {exc}")
    return success(f"Converted {blob_id} to {tissue.id}.", value=tissue)


def _legacy_geometry(context, blob):
    proxy = blob_proxy_for_context(context, blob)
    return None if proxy is None else _world_geometry(proxy)


def _preflight(blob):
    if blob is None:
        return "Select a legacy Blob VCP first."
    if str(blob.shape) not in {"SPHERE", "ELLIPSOID"}:
        return "Only sphere and ellipsoid Blobs can be converted."
    if str(blob.attach_target_type) not in {"NONE", "SCP"}:
        return "Muscle and object Blob targets are not supported."
    if (Vector(blob.control_point_world) - Vector(blob.center_world)).length > 1.0e-6:
        return "Off-center Blob controls cannot be converted safely."
    return ""


def _create_candidate(root, scene, blob):
    point = bpy.data.objects.new(f"AF_{blob.id}_POINT", None)
    point.location = Vector(blob.center_world)
    scene.collection.objects.link(point)
    tissues = root.af_vcp_system.soft_tissues
    tissue = tissues.add()
    with suppress_vcp_prop_updates():
        _map_blob(tissue, tissues, point, blob)
    return tissue, point


def _map_blob(tissue, tissues, point, blob):
    model = closed_bulk_model_from_legacy(_legacy_spec(blob))
    tissue.id = next_prefixed_id(tissues, "TISSUE")
    tissue.name, tissue.preset = model.name, model.preset.value
    tissue.base_domain, tissue.base_object_ref, tissue.base_owned = "POINT", point, True
    tissue.boundary_mode = model.boundary.value
    tissue.host_scp_id = str(blob.attach_target_id) if blob.attach_target_type == "SCP" else ""
    _assign_closed_bulk_fields(tissue, model)


def _legacy_spec(blob):
    kind = TargetKind.SCP if str(blob.attach_target_type) == "SCP" else TargetKind.NONE
    surface = TargetSurface.SCP_GEOMETRY if kind == TargetKind.SCP else TargetSurface.AUTO
    attachment = AttachmentSpec(kind, str(blob.attach_target_id or ""), surface)
    return LegacyBlobSpec(str(blob.id), str(blob.name), tuple(blob.center_world), float(blob.radius),
                          str(blob.shape), tuple(blob.axis_scale), int(blob.resolution), tuple(blob.gravity_dir),
                          float(blob.sag_strength), float(blob.sag_limit), float(blob.stiffness), int(blob.iterations), attachment)


def _assign_closed_bulk_fields(tissue, model):
    tissue.inflation_mode, tissue.inflation_amount = model.inflation.mode.value, model.inflation.amount
    tissue.axis_scale, tissue.base_resolution = model.inflation.scale, model.base.resolution
    tissue.gravity, tissue.sagginess = model.relaxation.gravity, model.relaxation.sagginess
    tissue.sag_limit, tissue.shape_retention = model.relaxation.sag_limit, model.material.shape_retention
    tissue.volume_retention, tissue.iterations = model.material.volume_retention, model.solver.iterations
    tissue.constraint_passes, tissue.tolerance = model.solver.constraint_passes, model.solver.tolerance
    tissue.relaxation_mode = model.solver.mode.value


def _sync_candidate(root, scene, tissue_id):
    from ...app.runtime_api import sync_scene
    from ...core.deps.dirty_hints import dirty_hints_for
    payload = {"soft_tissue_force": True, "soft_tissue_recapture_ids": [tissue_id]}
    sync_scene(root, scene, dirty_hints_for("SOFT_TISSUE", {tissue_id}), source="operator",
               event_type="SOFT_TISSUE_UPDATE", payload=payload)


def _validate_candidate(context, tissue, old):
    if soft_tissue_status(tissue) != "CLEAN":
        raise ValueError("the candidate failed to evaluate")
    proxy = soft_tissue_proxy_for_context(context, tissue)
    new = _world_geometry(proxy)
    if old[1] != new[1] or len(old[0]) != len(new[0]):
        raise ValueError("topology differs from the legacy Blob")
    error = max(((a - b).length for a, b in zip(old[0], new[0])), default=0.0)
    if error > 2.0e-6:
        raise ValueError(f"maximum vertex error {error:.3g} exceeds 2e-6")
    _validate_volume(old, new)


def _validate_volume(old, new):
    triangles = triangulate_faces(old[1])
    before = abs(mesh_volume(tuple(tuple(v) for v in old[0]), triangles))
    after = abs(mesh_volume(tuple(tuple(v) for v in new[0]), triangles))
    relative = abs(after - before) / max(before, 1.0e-12)
    if relative > 1.0e-6:
        raise ValueError(f"relative volume error {relative:.3g} exceeds 1e-6")


def _world_geometry(obj):
    if obj is None or obj.type != "MESH":
        raise ValueError("evaluated mesh is missing")
    vertices = tuple(obj.matrix_world @ vertex.co for vertex in obj.data.vertices)
    faces = tuple(tuple(poly.vertices) for poly in obj.data.polygons)
    return vertices, faces


def _commit_candidate(root, scene, blob, tissue):
    blob_id = str(blob.id)
    _remove_blob_objects(scene, root.name, blob_id)
    index = next(i for i, item in enumerate(root.af_vcp_system.blobs) if item.id == blob_id)
    with suppress_vcp_prop_updates():
        root.af_vcp_system.blobs.remove(index)
        root.af_vcp_system.active_vcp_type = "SOFT_TISSUE"
        root.af_vcp_system.active_vcp_id = str(tissue.id)


def _remove_blob_objects(scene, root_name, blob_id):
    for obj in tuple(scene.objects):
        same = obj.get("af_root_name") == root_name and obj.get("af_blob_id") == blob_id
        if same and (obj.get("af_blob_proxy") or obj.get("af_blob_control_gizmo")):
            _remove_object(obj)


def _rollback_candidate(root, scene, tissue, point):
    tissue_id = str(tissue.id)
    for obj in tuple(scene.objects):
        if obj.get("af_soft_tissue_id") == tissue_id and obj.get("af_root_name") == root.name:
            _remove_object(obj)
    index = next((i for i, item in enumerate(root.af_vcp_system.soft_tissues) if item.id == tissue_id), -1)
    if index >= 0:
        root.af_vcp_system.soft_tissues.remove(index)
    _remove_point_if_alive(point)


def _remove_point_if_alive(point):
    try:
        alive = point is not None and point.name in bpy.data.objects
    except ReferenceError:
        alive = False
    if alive:
        _remove_object(point)


def _remove_object(obj):
    data = getattr(obj, "data", None)
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0 and isinstance(data, bpy.types.Mesh):
        bpy.data.meshes.remove(data)

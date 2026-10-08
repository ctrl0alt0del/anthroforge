import json
import re
from dataclasses import asdict

import bpy

from ..shortcuts.owner_backsolve import owner_backsolve_enabled
from ..shortcuts.path_codec import make_bound_entity_id, make_shortcut_path, parse_shortcut_path
from ..units import unit_contract_payload
from ..utils import get_af_root
from ..vcp.muscle_inflation_state import migrate_inflation_control
from .model import (
    BlobSnapshot,
    BoundObjectSnapshot,
    FiberLoopAnchorSnapshot,
    FiberSnapshot,
    FiberSurfaceSnapshot,
    FiberTouchSnapshot,
    MuscleSnapshot,
    PackageSnapshot,
    ScpSnapshot,
    ShortcutSnapshot,
    ShortcutOverrideSnapshot,
    SoftTissueAttachmentSnapshot,
    SoftTissueSnapshot,
)
from .rna import scalar_dict

_FULL_OBJECT_RE = re.compile(r"^bpy\.data\.objects\[(['\"])(.+?)\1\](.+)$")
_SCP_SKIP = {"id", "name", "parent_id", "bound_objects", "transform_object_ref", "geometry_object_ref"}
_FIBER_SKIP = {"id", "name", "a_parent_id", "b_parent_id", "mid_touches", "loop_anchors", "muscle_id",
               "not_converged", "last_recompute_ms", "last_recompute_status", "last_eps_disp", "last_eps_pen",
               "legacy_points_json", "legacy_diagnostics_json", "legacy_status", "legacy_eps_disp", "legacy_eps_pen"}
_MUSCLE_SKIP = {"id", "name", "fiber_refs", "fiber_surface_id"}
_FIBER_SURFACE_SKIP = {"id", "name", "fiber_refs", "active_fiber_ref_index"}
_BLOB_SKIP = {"id", "name", "attach_target_type", "attach_target_id", "attach_target_object_name", "last_solve_converged", "last_solve_max_disp", "last_solve_iterations"}
_SOFT_SKIP = {"id", "name", "base_object_ref", "host_scp_id", "attachment_target_type",
              "attachment_target_id", "attachment_target_surface", "base_source_type", "base_source_id",
              "attachments", "active_attachment_index"}


def _bound_objects(scp):
    out = []
    for entry in scp.bound_objects:
        obj = getattr(entry, "object_ref", None)
        if obj is not None:
            out.append(BoundObjectSnapshot(str(entry.id or ""), str(entry.label or ""), str(obj.name)))
    return out


def _role_bound_id(scp, attr):
    target = getattr(scp, attr, None)
    for entry in scp.bound_objects:
        if getattr(entry, "object_ref", None) == target:
            return str(entry.id or "")
    return ""


def _mesh_topology(obj):
    mesh = getattr(obj, "data", None)
    if obj is None or getattr(obj, "type", "") != "MESH" or mesh is None:
        return None
    return {
        "vertices": len(mesh.vertices),
        "edges": len(mesh.edges),
        "faces": len(mesh.polygons),
        "loops": len(mesh.loops),
    }


def _object_tail(raw):
    match = _FULL_OBJECT_RE.match(str(raw or "").strip())
    if match is None:
        return None, ""
    return bpy.data.objects.get(match.group(2)), str(match.group(3) or "").lstrip(".")


def _bound_entity(root, obj):
    for scp in root.af_scp_system.scps:
        for entry in scp.bound_objects:
            if getattr(entry, "object_ref", None) == obj:
                return make_bound_entity_id(scp.id, entry.id)
    return ""


def _canonical_path(root, raw):
    kind, _entity, _prop = parse_shortcut_path(raw)
    if kind and kind != "object_rna":
        return str(raw or "")
    obj, tail = _object_tail(raw)
    entity = _bound_entity(root, obj)
    return str(raw or "") if obj is None or not tail or not entity else make_shortcut_path("scp_bound_rna", tail, entity_id=entity)


def _blob_entity(root, blob):
    obj = bpy.data.objects.get(str(blob.attach_target_object_name or ""))
    return "" if str(blob.attach_target_type) != "OBJECT" else _bound_entity(root, obj)


def _scp_snapshot(scp):
    return ScpSnapshot(
        source_id=str(scp.id or ""),
        name=str(scp.name or ""),
        parent_id=str(scp.parent_id or ""),
        props=scalar_dict(scp, _SCP_SKIP),
        transform_bound_id=_role_bound_id(scp, "transform_object_ref"),
        geometry_bound_id=_role_bound_id(scp, "geometry_object_ref"),
        topology=_mesh_topology(getattr(scp, "geometry_object_ref", None)),
        bound_objects=_bound_objects(scp),
    )


def _fiber_snapshot(fiber):
    touches = [FiberTouchSnapshot(str(tp.parent_id or ""), scalar_dict(tp, {"parent_id", "point_id"})) for tp in fiber.mid_touches]
    anchors = [FiberLoopAnchorSnapshot(str(item.parent_id or ""), scalar_dict(item, {"parent_id", "point_id"})) for item in getattr(fiber, "loop_anchors", ())]
    return FiberSnapshot(str(fiber.id or ""), str(fiber.name or ""), scalar_dict(fiber, _FIBER_SKIP | {'a_point_id', 'b_point_id'}), str(fiber.a_parent_id or ""), str(fiber.b_parent_id or ""), str(fiber.muscle_id or ""), touches, anchors)


def _muscle_snapshot(muscle):
    if muscle.inflation_mode in ("CTRL_POINT", "DISTRIBUTED"):
        migrate_inflation_control(muscle)
    ids = [str(ref.fiber_id or "") for ref in muscle.fiber_refs if str(ref.fiber_id or "")]
    return MuscleSnapshot(str(muscle.id or ""), str(muscle.name or ""), scalar_dict(muscle, _MUSCLE_SKIP), ids,
                          str(getattr(muscle, "fiber_surface_id", "") or ""))


def _fiber_surface_snapshot(surface):
    from ..vcp.free_surface_stations import KEY
    ids = [str(ref.fiber_id or "") for ref in surface.fiber_refs if str(ref.fiber_id or "")]
    return FiberSurfaceSnapshot(str(surface.id or ""), str(surface.name or ""),
                                scalar_dict(surface, _FIBER_SURFACE_SKIP), ids, str(surface.get(KEY, '')))


def _blob_snapshot(root, blob):
    return BlobSnapshot(str(blob.id or ""), str(blob.name or ""), scalar_dict(blob, _BLOB_SKIP), str(blob.attach_target_type or "NONE"), str(blob.attach_target_id or ""), str(blob.attach_target_object_name or ""), _blob_entity(root, blob))


def _soft_tissue_snapshot(tissue):
    base = getattr(tissue, "base_object_ref", None)
    rows = [SoftTissueAttachmentSnapshot(scalar_dict(row)) for row in tissue.attachments]
    return SoftTissueSnapshot(
        str(tissue.id or ""), str(tissue.name or ""), scalar_dict(tissue, _SOFT_SKIP),
        host_scp_id=str(tissue.host_scp_id or ""),
        attachment_target_type=str(getattr(tissue, "attachment_target_type", "NONE")),
        attachment_target_id=str(getattr(tissue, "attachment_target_id", "") or ""),
        attachment_target_surface=str(getattr(tissue, "attachment_target_surface", "AUTO")),
        base_object_name="" if base is None else str(base.name),
        base_source_type=str(getattr(tissue, "base_source_type", "OBJECT")),
        base_source_id=str(getattr(tissue, "base_source_id", "") or ""), attachments=rows,
        cache_object_names=_soft_cache_names(tissue))


def _soft_cache_names(tissue):
    if int(getattr(tissue, "evaluation_revision", 0)) >= 1:
        return []
    return [obj.name for obj in bpy.data.objects if obj.get("af_root_name") == tissue.id_data.name
            and obj.get("af_soft_tissue_id") == tissue.id
            and (obj.get("af_soft_tissue_proxy") or obj.get("af_soft_tissue_rest_proxy"))]


def _shortcut_snapshot(root, shortcut):
    return ShortcutSnapshot(str(shortcut.name or ""), str(shortcut.owner_type or "NONE"), str(shortcut.owner_id or ""), _canonical_path(root, shortcut.data_path), str(getattr(shortcut, "vector_mode", "DEFAULT") or "DEFAULT"), owner_backsolve_enabled(shortcut), _shortcut_overrides(shortcut))


def _shortcut_overrides(shortcut):
    return [ShortcutOverrideSnapshot(str(item.target_scp_id or ""), str(item.parent_anchor_mode or "KEEP"), str(item.child_anchor_mode or "KEEP"), str(getattr(item, "follow_rotation_mode", "KEEP") or "KEEP"), str(getattr(item, "rotation_strategy", "KEEP") or "KEEP")) for item in shortcut.overrides if str(item.target_scp_id or "")]


def root_snapshot(root):
    from ..muscle_relationships.importing import export
    from .branching import capture_graph; vcp = root.af_vcp_system
    return PackageSnapshot(
        root_name=str(root.name or "AF_ROOT"), branching=capture_graph(root), relationships=export(root),
        unit_contract=unit_contract_payload(root),
        draft_skin_settings=scalar_dict(root.af_draft_skin_settings), topology_settings=scalar_dict(root.af_topology_settings),
        scps=[_scp_snapshot(scp) for scp in root.af_scp_system.scps],
        fibers=[_fiber_snapshot(fiber) for fiber in vcp.fibers],
        fiber_surfaces=[_fiber_surface_snapshot(surface) for surface in getattr(vcp, "fiber_surfaces", ())],
        muscles=[_muscle_snapshot(muscle) for muscle in vcp.muscles],
        blobs=[_blob_snapshot(root, blob) for blob in vcp.blobs],
        soft_tissues=[_soft_tissue_snapshot(tissue) for tissue in vcp.soft_tissues],
        shortcuts=[_shortcut_snapshot(root, item) for item in root.af_shortcut_system.shortcuts],
    )


def write_snapshot_json(filepath):
    root = get_af_root(_snapshot_scene())
    if root is None:
        raise RuntimeError("No AnthroForge root found in source file.")
    with open(filepath, "w", encoding="utf-8") as handle:
        json.dump(asdict(root_snapshot(root)), handle, indent=2)


def _snapshot_scene():
    scenes = tuple(bpy.data.scenes)
    return None if not scenes else scenes[0]

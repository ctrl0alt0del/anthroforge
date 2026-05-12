import json
import re
from dataclasses import asdict

import bpy

from ..shortcuts.path_codec import make_bound_entity_id, make_shortcut_path, parse_shortcut_path
from ..utils import get_af_root
from .model import (
    BlobSnapshot,
    BoundObjectSnapshot,
    FiberSnapshot,
    FiberTouchSnapshot,
    MuscleSnapshot,
    PackageSnapshot,
    ScpSnapshot,
    ShortcutSnapshot,
)
from .rna import scalar_dict

_FULL_OBJECT_RE = re.compile(r"^bpy\.data\.objects\[(['\"])(.+?)\1\](.+)$")
_SCP_SKIP = {"id", "name", "parent_id", "bound_objects", "transform_object_ref", "geometry_object_ref"}
_FIBER_SKIP = {"id", "name", "a_parent_id", "b_parent_id", "mid_touches", "muscle_id", "not_converged", "last_recompute_ms", "last_recompute_status", "last_eps_disp", "last_eps_pen"}
_MUSCLE_SKIP = {"id", "name", "fiber_refs"}
_BLOB_SKIP = {"id", "name", "attach_target_type", "attach_target_id", "attach_target_object_name", "last_solve_converged", "last_solve_max_disp", "last_solve_iterations"}


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
        bound_objects=_bound_objects(scp),
    )


def _fiber_snapshot(fiber):
    touches = [FiberTouchSnapshot(str(tp.parent_id or ""), scalar_dict(tp, {"parent_id"})) for tp in fiber.mid_touches]
    return FiberSnapshot(str(fiber.id or ""), str(fiber.name or ""), scalar_dict(fiber, _FIBER_SKIP), str(fiber.a_parent_id or ""), str(fiber.b_parent_id or ""), str(fiber.muscle_id or ""), touches)


def _muscle_snapshot(muscle):
    ids = [str(ref.fiber_id or "") for ref in muscle.fiber_refs if str(ref.fiber_id or "")]
    return MuscleSnapshot(str(muscle.id or ""), str(muscle.name or ""), scalar_dict(muscle, _MUSCLE_SKIP), ids)


def _blob_snapshot(root, blob):
    return BlobSnapshot(str(blob.id or ""), str(blob.name or ""), scalar_dict(blob, _BLOB_SKIP), str(blob.attach_target_type or "NONE"), str(blob.attach_target_id or ""), str(blob.attach_target_object_name or ""), _blob_entity(root, blob))


def _shortcut_snapshot(root, shortcut):
    return ShortcutSnapshot(str(shortcut.name or ""), str(shortcut.owner_type or "NONE"), str(shortcut.owner_id or ""), _canonical_path(root, shortcut.data_path))


def root_snapshot(root):
    vcp = root.af_vcp_system
    return PackageSnapshot(
        root_name=str(root.name or "AF_ROOT"),
        scps=[_scp_snapshot(scp) for scp in root.af_scp_system.scps],
        fibers=[_fiber_snapshot(fiber) for fiber in vcp.fibers],
        muscles=[_muscle_snapshot(muscle) for muscle in vcp.muscles],
        blobs=[_blob_snapshot(root, blob) for blob in vcp.blobs],
        shortcuts=[_shortcut_snapshot(root, item) for item in root.af_shortcut_system.shortcuts],
    )


def write_snapshot_json(filepath):
    root = get_af_root(bpy.context.scene)
    if root is None:
        raise RuntimeError("No AnthroForge root found in source file.")
    with open(filepath, "w", encoding="utf-8") as handle:
        json.dump(asdict(root_snapshot(root)), handle, indent=2)

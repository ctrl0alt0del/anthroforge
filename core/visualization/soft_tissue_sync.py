import hashlib
import json
import time
from dataclasses import dataclass

import bpy
from mathutils import Vector

from ..deps.dirty_hints import dirty_hints_for
from ..utils import get_af_root, scene_for_id
from ..vcp.attachment_backend import attachment_runtime, capture_attachment_from_world, resolve_attachment_normal, resolve_attachment_world
from ..vcp.prop_update_guard import suppress_vcp_prop_updates
from ..vcp.runtime_state import set_soft_tissue_diagnostic, set_soft_tissue_status
from ..vcp.soft_tissue_model import construction_mode_for_domain
from ..vcp.surface_target import SurfaceTargetKind, effective_tissue_target
from .blob_sync_helpers import get_vis_collection, remove_proxy, update_mesh_from_world
from .soft_tissue_build import (
    build_rest_shape, capture_attachment_payload, capture_target_attachment_payloads, relax_shape,
    resolve_attachment_anchors, resolve_target_attachment_anchors,
)
from .soft_tissue_source import (
    apply_control_bindings, apply_control_pose, capture_control_bindings, capture_sample_bindings,
    capture_target_control_bindings, capture_target_sample_bindings, host_object, host_signature,
    infer_base_domain, resolve_sample_bindings, resolve_target_control_pose,
    resolve_target_sample_bindings, sample_base, sample_entity_base, validate_entity_source,
)
from .surface_target_service import default_surface_target_service


@dataclass(frozen=True)
class TissueEvaluation:
    rest: object
    final: object
    sample: object
    target_signature: str = ""
    control_bindings: str = None
    base_bindings: str = None
    region_bindings: tuple = None
    control_pose: object = None


class SoftTissueSceneSync:
    def __init__(self, collection_name="AF_VCP_VIS", target_service=None):
        self.collection_name = collection_name
        self.target_service = target_service or default_surface_target_service()
        self._syncing = False

    def sync_root_to_scene(self, root=None, scene=None, target_ids=None, recapture_ids=None, force=False):
        scene = scene or scene_for_id(root)
        root = root or get_af_root(scene)
        if root is None or not hasattr(root, "af_vcp_system"):
            return
        ids = None if target_ids is None else set(target_ids)
        recapture = _recapture_scopes(recapture_ids)
        self._syncing = True
        try:
            _sync_tissues(self, root, scene, ids, recapture, bool(force))
        finally:
            self._syncing = False

    def on_depsgraph_update(self, scene, depsgraph):
        if self._syncing:
            return
        root = get_af_root(scene)
        changed = _changed_source_ids(root, depsgraph)
        missing = _missing_proxy_ids(root, scene)
        if changed or missing:
            _schedule_updates(root, scene, changed | missing, changed)


def _recapture_scopes(value):
    if isinstance(value, dict):
        return {str(key): str(scope) for key, scope in value.items()}
    return {str(tissue_id): "ALL" for tissue_id in set(value or ())}


def _sync_tissues(sync, root, scene, ids, recapture, force):
    collection = get_vis_collection(scene, sync.collection_name)
    live = {str(item.id) for item in root.af_vcp_system.soft_tissues}
    _remove_stale_proxies(collection, root.name, live)
    for tissue in root.af_vcp_system.soft_tissues:
        if ids is None or str(tissue.id) in ids:
            _sync_one(sync, root, scene, collection, tissue, recapture.get(str(tissue.id), "NONE"), force)


def _sync_one(sync, root, scene, collection, tissue, recapture, force):
    _normalize_construction(tissue)
    if not bool(tissue.auto_recompute) and not force:
        set_soft_tissue_status(tissue, "DIRTY")
        return
    started = time.perf_counter()
    set_soft_tissue_status(tissue, "SOLVING")
    try:
        result = _evaluate_tissue(sync, root, scene, tissue, recapture)
        _write_tissue_objects(root, collection, tissue, result.rest, result.final)
        _commit_evaluation(tissue, result)
        _finish_success(tissue, started, result.final)
    except Exception as exc:
        _finish_error(tissue, started, exc)


def _normalize_construction(tissue):
    domain = _source_domain(tissue)
    expected = construction_mode_for_domain(domain).value
    with suppress_vcp_prop_updates():
        tissue.base_domain, tissue.inflation_mode = domain, expected
        tissue.tolerance = min(1.0e-2, max(1.0e-9, float(tissue.tolerance)))
        if domain == "POINT":
            tissue.boundary_mode = "CLOSED"


def _source_domain(tissue):
    source_type = str(getattr(tissue, "base_source_type", "OBJECT") or "OBJECT")
    if source_type == "FIBER":
        return "CURVE"
    if source_type == "FIBER_SURFACE":
        return "SURFACE"
    return infer_base_domain(tissue.base_object_ref) or str(tissue.base_domain)


def _evaluate_tissue(sync, root, scene, tissue, recapture):
    if int(getattr(tissue, "schema_version", 1)) < 2:
        return _evaluate_legacy_tissue(root, scene, tissue, recapture == "ALL")
    return _evaluate_generic_tissue(sync, root, scene, tissue, recapture)


def _evaluate_legacy_tissue(root, scene, tissue, recapture):
    errors = validate_entity_source(root, tissue)
    errors += _construction_errors(tissue)
    if errors:
        raise ValueError(" ".join(errors))
    target = host_object(root, scene, tissue)
    resolved = _prepare_host_bindings(root, scene, tissue, target, recapture)
    sample = _sample_tissue_base(root, scene, tissue, resolved)
    rest = build_rest_shape(tissue, sample)
    anchors = _prepare_attachments(root, scene, tissue, rest, recapture)
    return TissueEvaluation(rest, relax_shape(tissue, rest, target, anchors), sample)


def _evaluate_generic_tissue(sync, root, scene, tissue, recapture):
    errors = validate_entity_source(root, tissue) + _construction_errors(tissue)
    if errors:
        raise ValueError(" ".join(errors))
    runtime = attachment_runtime(scene)
    target = sync.target_service.resolve(root, scene, effective_tissue_target(tissue), runtime)
    _require_target_topology(tissue, target, recapture)
    sample, controls, base, pose = _prepare_generic_base(root, scene, tissue, target, runtime, recapture)
    rest = build_rest_shape(tissue, sample)
    anchors, regions = _prepare_generic_regions(tissue, rest, target, runtime, recapture)
    final = relax_shape(tissue, rest, None if target is None else target.mesh_object, anchors)
    signature = "" if target is None else target.topology_signature
    return TissueEvaluation(rest, final, sample, signature, controls, base, regions, pose)


def _require_target_topology(tissue, target, recapture):
    if target is None or recapture == "ALL":
        return
    stored = str(getattr(tissue, "attachment_topology_signature", "") or "")
    if not stored or stored != target.topology_signature:
        raise ValueError("Attachment target topology changed. Use Rebind.")


def _prepare_generic_base(root, scene, tissue, target, runtime, recapture):
    if str(getattr(tissue, "base_source_type", "OBJECT")) != "OBJECT":
        return sample_entity_base(root, scene, tissue), None, None, None
    if target is None:
        return sample_base(tissue.base_object_ref, tissue, scene=scene), None, None, None
    if recapture in {"ALL", "BASE"}:
        sample = sample_base(tissue.base_object_ref, tissue, scene=scene)
        controls = capture_target_control_bindings(target, tissue.base_object_ref, runtime)
        base = capture_target_sample_bindings(target, sample, runtime)
    else:
        controls, base = None, None
    source = base or tissue.base_bindings_json
    resolved = resolve_target_sample_bindings(target, source, runtime)
    pose = resolve_target_control_pose(target, tissue.base_object_ref,
                                       controls or tissue.control_bindings_json, runtime)
    return sample_base(tissue.base_object_ref, tissue, resolved, scene), controls, base, pose


def _prepare_generic_regions(tissue, rest, target, runtime, recapture):
    if target is None or not len(tissue.attachments):
        return (), None
    payloads = None
    if recapture in {"ALL", "REGIONS"}:
        payloads = capture_target_attachment_payloads(tissue, rest, target, runtime)
    anchors = resolve_target_attachment_anchors(tissue, rest, target, runtime, payloads)
    return anchors, payloads


def _commit_evaluation(tissue, result):
    if int(getattr(tissue, "schema_version", 1)) < 2:
        return
    if result.control_pose is not None:
        _commit_control_pose(tissue, result.control_pose)
    with suppress_vcp_prop_updates():
        tissue.attachment_topology_signature = result.target_signature
        tissue.base_signature = _sample_signature(result.sample)
        tissue.base_closed = bool(result.sample.cyclic or not result.sample.boundary_edges)
        if result.control_bindings is not None:
            tissue.control_bindings_json = result.control_bindings
        if result.base_bindings is not None:
            tissue.base_bindings_json = result.base_bindings
        _commit_region_bindings(tissue, result.region_bindings)


def _commit_control_pose(tissue, pose):
    obj = tissue.base_object_ref
    if obj is None:
        return
    _GUARDED_SOURCE_PTRS.add(int(obj.as_pointer()))
    apply_control_pose(obj, pose)


def _commit_region_bindings(tissue, payloads):
    if payloads is None:
        return
    for attachment, raw in zip(tissue.attachments, payloads):
        attachment.bindings_json = raw


def _sample_tissue_base(root, scene, tissue, resolved):
    if str(getattr(tissue, "base_source_type", "OBJECT")) != "OBJECT":
        return sample_entity_base(root, scene, tissue)
    return sample_base(tissue.base_object_ref, tissue, resolved, scene)


def _construction_errors(tissue):
    domain = str(tissue.base_domain)
    expected = construction_mode_for_domain(domain)
    mode = None if expected is None else expected.value
    errors = [] if str(tissue.inflation_mode) == mode else [f"{domain} requires {mode} inflation."]
    if domain == "POINT" and str(tissue.boundary_mode) != "CLOSED":
        errors.append("Point tissue requires a closed boundary.")
    return tuple(errors)


def _prepare_host_bindings(root, scene, tissue, target, recapture):
    if str(getattr(tissue, "base_source_type", "OBJECT")) != "OBJECT":
        return None
    if not str(tissue.host_scp_id or ""):
        return None
    if target is None:
        raise ValueError("Host SCP geometry is missing.")
    current = host_signature(target, scene)
    if not recapture and tissue.host_topology_signature and current != tissue.host_topology_signature:
        raise ValueError("Host SCP topology changed. Use Rebind.")
    stale = not _sample_bindings_match(tissue, scene)
    return _recapture_base(root, scene, tissue, current) if recapture or stale else _resolve_base(root, scene, tissue)


def _sample_bindings_match(tissue, scene):
    count = _binding_count(tissue.base_bindings_json)
    expected = len(sample_base(tissue.base_object_ref, tissue, scene=scene).points)
    return bool(count and count == expected)


def _binding_count(raw):
    try:
        value = json.loads(str(raw or "[]"))
    except Exception:
        return 0
    values = value.get("bindings", ()) if isinstance(value, dict) else value
    return len(values) if isinstance(values, (list, tuple)) else 0


def _recapture_base(root, scene, tissue, signature):
    sample = sample_base(tissue.base_object_ref, tissue, scene=scene)
    with suppress_vcp_prop_updates():
        tissue.control_bindings_json = capture_control_bindings(root, scene, tissue)
        tissue.base_bindings_json = capture_sample_bindings(root, scene, tissue, sample)
        tissue.host_topology_signature = signature
        tissue.base_signature = _sample_signature(sample)
        tissue.base_closed = bool(sample.cyclic or not sample.boundary_edges)
    return resolve_sample_bindings(root, scene, tissue)


def _resolve_base(root, scene, tissue):
    _GUARDED_SOURCE_PTRS.add(int(tissue.base_object_ref.as_pointer()))
    apply_control_bindings(root, scene, tissue)
    return resolve_sample_bindings(root, scene, tissue)


def _prepare_attachments(root, scene, tissue, rest, recapture):
    if not str(tissue.host_scp_id or "") or not len(tissue.attachments):
        return ()
    if recapture or any(not _has_bindings(row.bindings_json) for row in tissue.attachments):
        with suppress_vcp_prop_updates():
            capture_attachment_payload(root, scene, tissue, rest, capture_attachment_from_world)
    return resolve_attachment_anchors(root, scene, tissue, rest, resolve_attachment_world, resolve_attachment_normal)


def _write_tissue_objects(root, collection, tissue, rest, final):
    proxy = _ensure_proxy(collection, root, tissue, False)
    rest_proxy = _ensure_proxy(collection, root, tissue, True)
    update_mesh_from_world(proxy, [Vector(value) for value in final.vertices], rest.faces)
    update_mesh_from_world(rest_proxy, [Vector(value) for value in rest.vertices], rest.faces)
    rest_proxy.hide_viewport = not bool(tissue.show_rest)
    _tag_base(root, tissue)
    _lock_proxy(proxy)
    _lock_proxy(rest_proxy)


def _ensure_proxy(collection, root, tissue, rest):
    found = _find_proxy(collection, root.name, tissue.id, rest)
    if found is not None:
        return found
    suffix = "_REST" if rest else ""
    mesh = bpy.data.meshes.new(f"AF_{tissue.id}{suffix}_mesh")
    obj = bpy.data.objects.new(f"AF_{tissue.id}{suffix}", mesh)
    collection.objects.link(obj)
    _tag_proxy(obj, root.name, tissue.id, rest)
    return obj


def _tag_proxy(obj, root_name, tissue_id, rest):
    obj["af_soft_tissue_id"] = str(tissue_id)
    obj["af_root_name"] = str(root_name)
    obj["af_soft_tissue_rest_proxy" if rest else "af_soft_tissue_proxy"] = True


def _find_proxy(collection, root_name, tissue_id, rest):
    key = "af_soft_tissue_rest_proxy" if rest else "af_soft_tissue_proxy"
    return next((obj for obj in collection.objects if obj.get(key) and obj.get("af_root_name") == root_name
                 and obj.get("af_soft_tissue_id") == tissue_id), None)


def _remove_stale_proxies(collection, root_name, live):
    for obj in tuple(collection.objects):
        tagged = obj.get("af_soft_tissue_proxy") or obj.get("af_soft_tissue_rest_proxy")
        if tagged and obj.get("af_root_name") == root_name and obj.get("af_soft_tissue_id") not in live:
            remove_proxy(obj)


def _tag_base(root, tissue):
    obj = tissue.base_object_ref
    if obj is None or str(getattr(tissue, "base_source_type", "OBJECT")) != "OBJECT":
        return
    obj["af_soft_tissue_base"] = True
    obj["af_soft_tissue_id"] = str(tissue.id)
    obj["af_root_name"] = str(root.name)


def _lock_proxy(obj):
    obj.lock_location = (True, True, True)
    obj.lock_rotation = (True, True, True)
    obj.lock_scale = (True, True, True)


def _finish_success(tissue, started, final):
    elapsed = (time.perf_counter() - started) * 1000.0
    set_soft_tissue_diagnostic(tissue, elapsed, final.iterations, final.max_displacement, "")
    set_soft_tissue_status(tissue, "CLEAN")


def _finish_error(tissue, started, error):
    elapsed = (time.perf_counter() - started) * 1000.0
    set_soft_tissue_diagnostic(tissue, elapsed, error=str(error))
    set_soft_tissue_status(tissue, "ERROR")


def _sample_signature(sample):
    values = (sample.points, sample.normals, sample.faces, sample.boundary_edges,
              sample.weights, sample.cyclic, sample.groups or {})
    raw = json.dumps(values, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _has_bindings(raw):
    try:
        value = json.loads(str(raw or "[]"))
    except Exception:
        return False
    return bool(value.get("bindings")) if isinstance(value, dict) else bool(value)


def _changed_source_ids(root, depsgraph):
    if root is None or not hasattr(root, "af_vcp_system"):
        return set()
    updated = {item.id for item in depsgraph.updates}
    return {str(tissue.id) for tissue in root.af_vcp_system.soft_tissues if _artist_source_update(tissue, updated)}


def _artist_source_update(tissue, updated):
    source = tissue.base_object_ref
    changed = source in updated or getattr(source, "data", None) in updated
    pointer = 0 if source is None else int(source.as_pointer())
    if changed and pointer in _GUARDED_SOURCE_PTRS:
        _GUARDED_SOURCE_PTRS.discard(pointer)
        return False
    return bool(changed)


def _missing_proxy_ids(root, scene):
    if root is None or not hasattr(root, "af_vcp_system"):
        return set()
    final = _proxy_ids(scene, root.name, "af_soft_tissue_proxy")
    rest = _proxy_ids(scene, root.name, "af_soft_tissue_rest_proxy")
    return {str(tissue.id) for tissue in root.af_vcp_system.soft_tissues if str(tissue.id) not in final or str(tissue.id) not in rest}


def _proxy_ids(scene, root_name, key):
    return {str(obj.get("af_soft_tissue_id")) for obj in scene.objects
            if obj.get(key) and obj.get("af_root_name") == root_name}


def _schedule_updates(root, scene, ids, recapture):
    from ..visualization.sync_runner import schedule_sync_from_dirty_hints
    payload = {"soft_tissue_recapture_ids": sorted(recapture)} if recapture else {}
    schedule_sync_from_dirty_hints(root=root, scene=scene, dirty_hints=dirty_hints_for("SOFT_TISSUE", ids),
                                  source="depsgraph", event_type="SOFT_TISSUE_UPDATE", payload=payload)


_SOFT_TISSUE_SYNC = None
_GUARDED_SOURCE_PTRS = set()


def register_soft_tissue_sync():
    global _SOFT_TISSUE_SYNC
    if _SOFT_TISSUE_SYNC is None:
        _SOFT_TISSUE_SYNC = SoftTissueSceneSync(target_service=default_surface_target_service())
    handler = _SOFT_TISSUE_SYNC.on_depsgraph_update
    if handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(handler)
    return _SOFT_TISSUE_SYNC


def unregister_soft_tissue_sync():
    global _SOFT_TISSUE_SYNC
    if _SOFT_TISSUE_SYNC is None:
        return
    handler = _SOFT_TISSUE_SYNC.on_depsgraph_update
    if handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(handler)
    _SOFT_TISSUE_SYNC = None

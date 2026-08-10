import hashlib
import json
import time

import bpy
from mathutils import Vector

from ..deps.dirty_hints import dirty_hints_for
from ..utils import get_af_root, scene_for_id
from ..vcp.attachment_backend import capture_attachment_from_world, resolve_attachment_normal, resolve_attachment_world
from ..vcp.prop_update_guard import suppress_vcp_prop_updates
from ..vcp.runtime_state import set_soft_tissue_diagnostic, set_soft_tissue_status
from ..vcp.soft_tissue_model import construction_mode_for_domain
from .blob_sync_helpers import get_vis_collection, remove_proxy, update_mesh_from_world
from .soft_tissue_build import build_rest_shape, capture_attachment_payload, relax_shape, resolve_attachment_anchors
from .soft_tissue_source import apply_control_bindings, capture_control_bindings, capture_sample_bindings, host_object, host_signature, infer_base_domain, resolve_sample_bindings, sample_base, validate_source


class SoftTissueSceneSync:
    def __init__(self, collection_name="AF_VCP_VIS"):
        self.collection_name = collection_name
        self._syncing = False

    def sync_root_to_scene(self, root=None, scene=None, target_ids=None, recapture_ids=None, force=False):
        scene = scene or scene_for_id(root)
        root = root or get_af_root(scene)
        if root is None or not hasattr(root, "af_vcp_system"):
            return
        ids = None if target_ids is None else set(target_ids)
        recapture = set(recapture_ids or ())
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


def _sync_tissues(sync, root, scene, ids, recapture, force):
    collection = get_vis_collection(scene, sync.collection_name)
    live = {str(item.id) for item in root.af_vcp_system.soft_tissues}
    _remove_stale_proxies(collection, root.name, live)
    for tissue in root.af_vcp_system.soft_tissues:
        if ids is None or str(tissue.id) in ids:
            _sync_one(root, scene, collection, tissue, str(tissue.id) in recapture, force)


def _sync_one(root, scene, collection, tissue, recapture, force):
    _normalize_construction(tissue)
    if not bool(tissue.auto_recompute) and not force:
        set_soft_tissue_status(tissue, "DIRTY")
        return
    started = time.perf_counter()
    set_soft_tissue_status(tissue, "SOLVING")
    try:
        final = _evaluate_tissue(root, scene, tissue, recapture)
        _write_tissue_objects(root, collection, tissue, final[0], final[1])
        _finish_success(tissue, started, final[1])
    except Exception as exc:
        _finish_error(tissue, started, exc)


def _normalize_construction(tissue):
    source = tissue.base_object_ref
    domain = infer_base_domain(source) or str(tissue.base_domain)
    expected = construction_mode_for_domain(domain).value
    with suppress_vcp_prop_updates():
        tissue.base_domain, tissue.inflation_mode = domain, expected
        tissue.tolerance = min(1.0e-2, max(1.0e-9, float(tissue.tolerance)))
        if domain == "POINT":
            tissue.boundary_mode = "CLOSED"


def _evaluate_tissue(root, scene, tissue, recapture):
    source = tissue.base_object_ref
    errors = validate_source(source, tissue.base_domain)
    errors += _construction_errors(tissue)
    if errors:
        raise ValueError(" ".join(errors))
    target = host_object(root, scene, tissue)
    resolved = _prepare_host_bindings(root, scene, tissue, target, recapture)
    sample = sample_base(source, tissue, resolved, scene)
    rest = build_rest_shape(tissue, sample)
    anchors = _prepare_attachments(root, scene, tissue, rest, recapture)
    return rest, relax_shape(tissue, rest, target, anchors)


def _construction_errors(tissue):
    domain = str(tissue.base_domain)
    expected = construction_mode_for_domain(domain)
    mode = None if expected is None else expected.value
    errors = [] if str(tissue.inflation_mode) == mode else [f"{domain} requires {mode} inflation."]
    if domain == "POINT" and str(tissue.boundary_mode) != "CLOSED":
        errors.append("Point tissue requires a closed boundary.")
    return tuple(errors)


def _prepare_host_bindings(root, scene, tissue, target, recapture):
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
        _SOFT_TISSUE_SYNC = SoftTissueSceneSync()
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

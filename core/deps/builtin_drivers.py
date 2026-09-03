from .adapters import build_runtime_graph
from .drivers import DependencyDriver
from .runtime_intents import pop_runtime_intents
from .runtime_intent_behaviors import apply_runtime_intent
from .mirror_roles import apply_scp_mirror_roles
from ..visualization.scp_attachment_runtime import capture_authored_scp_attachments, capture_dirty_scp_attachments
from ..visualization.sync import register_sync
from ..visualization.fiber_sync import register_fiber_sync
from ..visualization.fiber_surface_sync import register_fiber_surface_sync
from ..visualization.muscle_sync import register_muscle_sync
from ..visualization.blob_sync import register_blob_sync
from ..visualization.soft_tissue_sync import register_soft_tissue_sync
from ..visualization.vcp_mirror_runtime import sync_vcp_mirrors


def _payload_id_set(payload, key):
    vals = (dict(payload or {})).get(str(key), ())
    out = set()
    for v in set(vals or ()):
        sid = str(v or "")
        if sid:
            out.add(sid)
    return out


def _scp_dirty_ids(ctx):
    return set(ctx.dirty.get("SCP", set()) or set())


def _meta_payload(meta):
    return dict(meta.get("payload", {}) or {})


def _scp_attachment_changes(ctx, scp_dirty):
    if _full_attachment_capture(ctx):
        return capture_authored_scp_attachments(ctx.root, ctx.scene)
    meta = dict(ctx.gate_meta or {})
    return capture_dirty_scp_attachments(
        root=ctx.root,
        scene=ctx.scene,
        dirty_scp_ids=scp_dirty,
        source=str(meta.get("source", "") or ""),
        recapture_ids=_payload_id_set(_meta_payload(meta), "scp_recapture_ids"),
        apply_parent_ids=_scp_parent_ids(meta),
    )


def _scp_parent_ids(meta):
    payload = _meta_payload(meta)
    return _payload_id_set(payload, "scp_apply_parent_ids")


def _payload_has_key(payload, key):
    return str(key) in dict(payload or {})


def _scp_target_ids(meta, fallback):
    payload = _meta_payload(meta)
    return _payload_id_set(payload, "scp_apply_target_ids") if _payload_has_key(payload, "scp_apply_target_ids") else set(fallback or set())


def _all_scp_parent_ids(root):
    return {str(getattr(scp, "parent_id", "") or "") for scp in root.af_scp_system.scps if str(getattr(scp, "parent_id", "") or "")}


def _full_attachment_capture(ctx):
    meta = dict(ctx.gate_meta or {})
    source = str(meta.get("source", "") or "").lower()
    event = str(meta.get("event_type", "") or "").upper()
    return bool(ctx.is_full and (source == "load" or event in {"LOAD", "IMPORT"}))


def _selection_event(meta):
    return str(dict(meta or {}).get("event_type", "") or "").upper() == "SELECTION"


def _load_event(meta):
    return str(dict(meta or {}).get("event_type", "") or "").upper() == "LOAD"


def _fiber_update_event(meta):
    return str(dict(meta or {}).get("event_type", "") or "").upper() == "FIBER_UPDATE"


def _fiber_quality(meta, bake=False):
    value = str(dict(meta or {}).get("quality", "") or "").upper()
    return "FINAL" if bake or value in {"BAKE", "FINAL"} else "INTERACTIVE"


def _sync_scp_scene(root, scene, ids, is_full, meta):
    parent_ids = _scp_parent_ids(meta) or (_all_scp_parent_ids(root) if is_full else set())
    target_ids = _scp_target_ids(meta, ids)
    kwargs = {"root": root, "scene": scene, "attachment_parent_ids": parent_ids, "attachment_gate_meta": meta}
    if is_full:
        register_sync().sync_root_to_scene(**kwargs)
    elif ids or target_ids or parent_ids:
        register_sync().sync_root_to_scene(target_scp_ids=target_ids, **kwargs)


class RuntimeGraphDriver(DependencyDriver):
    name = "runtime_graph_driver"

    def entity_types(self):
        return ("SCP", "FIBER", "FIBER_SURFACE", "MUSCLE", "BLOB", "SOFT_TISSUE", "CONTROL")

    def build_graph(self, root, graph, entity_sets):
        built = build_runtime_graph(root, graph)
        for et, ids in built.items():
            entity_sets.setdefault(et, set()).update(set(ids or set()))


class RuntimeIntentDriver(DependencyDriver):
    name = "runtime_intent_driver"

    def entity_types(self):
        return ("CONTROL", "SCP", "FIBER", "FIBER_SURFACE", "MUSCLE", "BLOB", "SOFT_TISSUE")

    def apply_constraints(self, ctx):
        merged = {}
        for intent in pop_runtime_intents(ctx.root):
            impacts = apply_runtime_intent(ctx.root, ctx.scene, intent) or {}
            for et, ids in impacts.items():
                merged.setdefault(et, set())
                merged[et] |= set(ids or set())
        return merged


class SCPMirrorRoleDriver(DependencyDriver):
    name = "scp_mirror_role_driver"

    def entity_types(self):
        return ("SCP",)

    def apply_constraints(self, ctx):
        scp_all = set(ctx.entity_sets.get("SCP", set()) or set())
        scp_dirty = set(ctx.dirty.get("SCP", set()) or set())
        changed_scps = scp_all if ctx.is_full else scp_dirty
        if not changed_scps:
            return {}

        changed = apply_scp_mirror_roles(ctx.root)
        if not changed:
            return {}
        return {"SCP": set(changed)}


class SCPAttachmentCaptureDriver(DependencyDriver):
    name = "scp_attachment_capture_driver"

    def entity_types(self):
        return ("SCP",)

    def apply_constraints(self, ctx):
        scp_dirty = _scp_dirty_ids(ctx)
        if not scp_dirty:
            return {}
        changed = _scp_attachment_changes(ctx, scp_dirty)
        if not changed:
            return {}
        return {"SCP": set(changed)}


class SCPSyncDriver(DependencyDriver):
    name = "scp_sync_driver"

    def entity_types(self):
        return ("SCP",)

    def sync(self, root, scene, is_full, impacted, bake, gate_meta=None):
        _ = bake
        if _selection_event(gate_meta):
            return
        ids = set(impacted.get("SCP", set()) or set())
        _sync_scp_scene(root, scene, ids, is_full, dict(gate_meta or {}))


class FiberSyncDriver(DependencyDriver):
    name = "fiber_sync_driver"

    def entity_types(self):
        return ("FIBER",)

    def sync(self, root, scene, is_full, impacted, bake, gate_meta=None):
        ids = set(impacted.get("FIBER", set()) or set())
        if _sync_special_fiber_event(root, scene, ids, bake, gate_meta): return
        _sync_impacted_fibers(root, scene, ids, is_full, bake, gate_meta)


def _sync_special_fiber_event(root, scene, ids, bake, meta):
    if _selection_event(meta):
        register_fiber_sync().refresh_selection(root=root, scene=scene, fiber_ids=ids, sync_handles=True)
        return True
    if _load_event(meta):
        _capture_loaded_fiber_nodes(root, scene, ids)
        register_fiber_sync().refresh_selection(root=root, scene=scene, sync_handles=True)
        return True
    if _fiber_update_event(meta):
        _sync_fiber_update(root, scene, ids, _fiber_quality(meta, bake)); return True
    return False


def _sync_impacted_fibers(root, scene, ids, is_full, bake, meta):
    solved = _solved_fiber_ids(meta)
    ids -= solved
    authored = _authored_fiber_ids(ids, meta, is_full)
    derived = ids - authored
    _sync_attached_fiber_nodes(root, scene, derived)
    if solved:
        register_fiber_sync().refresh_selection(root=root, scene=scene)
    _sync_unsolved_fibers(root, scene, False, authored, solved, bake,
                          not _deferred_fiber_event(meta)) if authored else None


def _sync_fiber_update(root, scene, ids, quality):
    register_fiber_sync().refresh_selection(root=root, scene=scene, fiber_ids=ids, sync_handles=True)
    _request_fiber_refinements(root, scene, ids, quality)


def _capture_loaded_fiber_nodes(root, scene, ids):
    from ..visualization.fiber_node_attachment_runtime import capture_missing_fiber_node_attachments
    return capture_missing_fiber_node_attachments(root, scene, ids or None)


def _sync_attached_fiber_nodes(root, scene, ids):
    if not ids: return set()
    from ..visualization.fiber_node_attachment_runtime import apply_fiber_node_attachments
    return set(apply_fiber_node_attachments(root, scene, ids) or set())


def _authored_fiber_ids(ids, meta, is_full):
    event = str(dict(meta or {}).get("event_type", "") or "").upper()
    if is_full and event == "IMPORT": return set(ids or ())
    return set(ids or ()) & _runtime_dirty_ids(meta, "FIBER")


def _runtime_dirty_ids(meta, entity_type):
    rows = dict(dict(meta or {}).get("runtime_dirty_ids_by_type", {}) or {})
    return {str(value or "") for value in rows.get(str(entity_type), ()) if str(value or "")}


def _request_fiber_refinements(root, scene, ids, quality):
    from ..visualization.fiber_refinement import request_fiber_refinement
    fibers = getattr(root.af_vcp_system, "fibers", ())
    by_id = {str(fiber.id): fiber for fiber in fibers}
    for fiber_id in sorted(set(ids or ())):
        fiber = by_id.get(str(fiber_id))
        if fiber is not None:
            request_fiber_refinement(root, scene, fiber, show_preview=True, quality=quality)


def _sync_unsolved_fibers(root, scene, is_full, ids, solved, bake, drain=True):
    sync = register_fiber_sync()
    if is_full and not solved:
        sync.sync_root_to_scene(root=root, scene=scene, bake=bake, drain=drain)
        return
    if is_full:
        ids |= {fiber.id for fiber in root.af_vcp_system.fibers} - solved
    if ids:
        sync.sync_root_to_scene(root=root, scene=scene, bake=bake,
                                target_fiber_ids=ids, drain=drain)


def _deferred_fiber_event(meta):
    return str(dict(meta or {}).get("source", "") or "").lower() == "shortcut"


def _solved_fiber_ids(gate_meta):
    meta = dict(gate_meta or {})
    if str(meta.get("event_type", "")) != "FIBER_SOLVE_READY":
        return set()
    return _payload_id_set(_meta_payload(meta), "solved_fiber_ids")


class MuscleSyncDriver(DependencyDriver):
    name = "muscle_sync_driver"

    def entity_types(self):
        return ("MUSCLE",)

    def sync(self, root, scene, is_full, impacted, bake, gate_meta=None):
        if _selection_event(gate_meta) or _fiber_update_event(gate_meta):
            return
        ids = set(impacted.get("MUSCLE", set()) or set())
        if is_full:
            register_muscle_sync().sync_root_to_scene(root=root, scene=scene)
        elif ids:
            register_muscle_sync().sync_root_to_scene(root=root, scene=scene, target_muscle_ids=ids)


class FiberSurfaceSyncDriver(DependencyDriver):
    name = "fiber_surface_sync_driver"

    def entity_types(self):
        return ("FIBER_SURFACE",)

    def sync(self, root, scene, is_full, impacted, bake, gate_meta=None):
        if _selection_event(gate_meta) or _fiber_update_event(gate_meta):
            return
        ids = set(impacted.get("FIBER_SURFACE", set()) or set())
        targets = None if is_full else ids
        if is_full or ids:
            register_fiber_surface_sync().sync_root_to_scene(root, scene, targets)


class BlobSyncDriver(DependencyDriver):
    name = "blob_sync_driver"

    def entity_types(self):
        return ("BLOB",)

    def sync(self, root, scene, is_full, impacted, bake, gate_meta=None):
        if _selection_event(gate_meta):
            return
        ids = set(impacted.get("BLOB", set()) or set())
        if is_full:
            register_blob_sync().sync_root_to_scene(root=root, scene=scene)
        elif ids:
            register_blob_sync().sync_root_to_scene(root=root, scene=scene, target_blob_ids=ids)


class SoftTissueSyncDriver(DependencyDriver):
    name = "soft_tissue_sync_driver"

    def entity_types(self):
        return ("SOFT_TISSUE",)

    def sync(self, root, scene, is_full, impacted, bake, gate_meta=None):
        if _selection_event(gate_meta) or _fiber_update_event(gate_meta):
            return
        if not len(root.af_vcp_system.soft_tissues):
            return
        ids = set(impacted.get("SOFT_TISSUE", set()) or set())
        payload = _meta_payload(dict(gate_meta or {}))
        recapture = _payload_id_set(payload, "soft_tissue_recapture_ids")
        base = _payload_id_set(payload, "soft_tissue_base_recapture_ids")
        regions = _payload_id_set(payload, "soft_tissue_region_recapture_ids")
        force = bool(payload.get("soft_tissue_force"))
        targets = None if is_full else ids
        scopes = {value: "ALL" for value in recapture}
        scopes.update({value: "BASE" for value in base - recapture})
        scopes.update({value: "REGIONS" for value in regions - recapture - base})
        register_soft_tissue_sync().sync_root_to_scene(root, scene, targets, scopes, force or _load_event(gate_meta))


class VCPMirrorSyncDriver(DependencyDriver):
    name = "vcp_mirror_sync_driver"

    def entity_types(self):
        return ("SCP", "FIBER", "MUSCLE", "BLOB", "SOFT_TISSUE")

    def _impacted_ids(self, impacted):
        return (
            set(impacted.get("FIBER", set()) or set()),
            set(impacted.get("MUSCLE", set()) or set()),
            set(impacted.get("BLOB", set()) or set()),
            set(impacted.get("SOFT_TISSUE", set()) or set()),
        )

    def _sync_targets(self, root, scene, fiber_ids, muscle_ids, blob_ids, tissue_ids):
        sync_vcp_mirrors(
            root=root,
            scene=scene,
            target_fiber_ids=fiber_ids,
            target_muscle_ids=muscle_ids,
            target_blob_ids=blob_ids,
            target_soft_tissue_ids=tissue_ids,
        )

    def sync(self, root, scene, is_full, impacted, bake, gate_meta=None):
        _ = bake
        if _selection_event(gate_meta) or _fiber_update_event(gate_meta):
            return
        fiber_ids, muscle_ids, blob_ids, tissue_ids = self._impacted_ids(impacted)
        if is_full:
            sync_vcp_mirrors(root=root, scene=scene)
            return
        if not fiber_ids and not muscle_ids and not blob_ids and not tissue_ids:
            return
        self._sync_targets(root, scene, fiber_ids, muscle_ids, blob_ids, tissue_ids)

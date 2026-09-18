"""Blender scene port with RNA ownership and reversible publication."""
from contextlib import contextmanager
import bpy
from ...core.authoring.codec import encode, decode, digest
from ...core.authoring.errors import require
from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates
from ...core.visualization.fiber_surface_sync import register_fiber_surface_sync
from ...core.visualization.muscle_sync import register_muscle_sync
from ...core.visualization.fiber_sync import register_fiber_sync
from ...core.visualization.vcp_mirror_runtime import sync_vcp_mirrors
from ...core.visualization.fiber_sync_helpers import persisted_fiber_points
from .capture import snapshot, native_records
from .native import write_muscle, find
from .records import record, restore
from .ownership import validate_removal, remove_proxies
from .publication import verify
from .symmetry import configure as configure_symmetry
from ...core.authoring.symmetry import mirror_planes


class BlenderScene:
    def __init__(self, root, scene):
        self.root, self.scene = root, scene

    def capture(self, scene_id):
        return snapshot(self.root, self.scene, scene_id)

    def documents(self):
        return [value["document"] for value in root_documents(self.root).values()]

    def document(self, identity):
        return root_documents(self.root).get(identity, {}).get("record")

    def persist(self, value):
        documents = root_documents(self.root)
        documents[value["document"]["document_id"]]["record"] = value
        self.root["af_authoring_documents"] = encode(documents)

    @contextmanager
    def publish(self, captured, document, outputs, previous):
        require(self.capture(captured.id).revision == captured.revision, "STALE_REVISION")
        planes = preflight(self, document, outputs, previous, captured)
        saved = memento(self, previous)
        objects = set(bpy.data.objects)
        try:
            with suppress_vcp_prop_updates():
                ids = write_outputs(self, document, outputs, previous, planes)
                self.refresh(ids)
                verify(self, ids, outputs, planes)
                remember(self, document, ids)
                yield ids
        except BaseException:
            rollback(self, saved, objects)
            raise

    def refresh(self, ids=None):
        targets = grouped(ids) if ids is not None else {}
        if any(s.construction_mode == 'BRANCHED_LOFT' for s in self.root.af_vcp_system.fiber_surfaces):
            targets = {}
        register_fiber_surface_sync().sync_root_to_scene(self.root, self.scene, targets.get("fiber_surfaces"))
        register_muscle_sync().sync_root_to_scene(self.root, self.scene, targets.get("muscles"))
        sync_vcp_mirrors(self.root,self.scene,targets.get("fibers"),targets.get("muscles"),(),())


def preflight(port, document, outputs, previous, captured):
    planes = mirror_planes(document, captured)
    _validate_output_offsets(outputs)
    documents = root_documents(port.root)
    saved = documents.get(document["document_id"])
    require(bool(saved) == bool(previous), "DOCUMENT_JOURNAL_MISMATCH")
    if saved:
        require(saved["fingerprint"] == ownership(port.root, saved["ids"]), "EXTERNAL_EDIT_CONFLICT")
    return planes


def _validate_output_offsets(outputs):
    from .branched_native import junction_fibers
    for output in outputs.values():
        shared = junction_fibers(output)
        for row in output['fibers']:
            require(all(abs(a['offset']) < 1e-10 for a in _constrained_ends(row, shared)), 'UNSUPPORTED_ANCHOR_OFFSET')


def _constrained_ends(row, junctions):
    if row['closed']:
        return row['anchors']
    return [row['anchors'][-1]] if row['id'] in junctions else [row['anchors'][0], row['anchors'][-1]]


def write_outputs(port, document, outputs, previous, planes):
    old = (previous or {}).get("native_ids", {})
    ids = {name: write_muscle(port.root, port.scene, name, output, old.get(name, {}),document) for name, output in outputs.items()}
    for name, identity in ids.items():
        configure_symmetry(port.root, identity, planes[name])
    remove_obsolete(port.root, old, ids)
    return ids


def grouped(ids):
    surfaces = {sid for r in ids.values() for sid in (r['surface'], *r.get('parts', {}).values())}
    return dict(muscles={r["muscle"] for r in ids.values()}, fiber_surfaces=surfaces,
                fibers={f for r in ids.values() for f in r["fibers"].values()})


def ownership(root, ids):
    records = {name: [owned_record(root, name, key) for key in sorted(keys)]
               for name, keys in grouped(ids).items()}
    records['authored_points'] = owned_points(root, grouped(ids)['fibers'])
    return digest(records)


def owned_points(root, fiber_ids):
    from ...core.vcp.shared_point_storage import slots
    keys = {getattr(owner, slot) for fiber in root.af_vcp_system.fibers if fiber.id in fiber_ids
            for owner, slot, _ in slots(fiber)}
    return [record(point) for point in sorted(root.af_vcp_system.authored_points, key=lambda p: p.id) if point.id in keys]


def owned_record(root, name, key):
    item = find(getattr(root.af_vcp_system,name),key)
    require(item is not None,"EXTERNAL_EDIT_CONFLICT",key)
    return record(item)


def remember(port, document, ids):
    documents = root_documents(port.root)
    documents[document["document_id"]] = dict(document=document, ids=ids, fingerprint=ownership(port.root, ids))
    port.root["af_authoring_documents"] = encode(documents)


def root_documents(root):
    return decode(root.get("af_authoring_documents", "{}"), 256_000_000)


def remove_obsolete(root, previous, current):
    wanted = grouped(current)
    validate_removal(root,grouped(previous),wanted)
    for name, keys in grouped(previous).items():
        collection = getattr(root.af_vcp_system, name)
        for index in reversed(range(len(collection))):
            if collection[index].id in keys - wanted[name]:
                collection.remove(index)
    remove_proxies(root,grouped(previous),wanted)


def rollback(port, saved, objects):
    with suppress_vcp_prop_updates():
        for name, rows in saved[0].items():
            collection = getattr(port.root.af_vcp_system, name)
            collection.clear()
            for row in rows:
                restore(collection.add(), row)
        port.root["af_authoring_documents"] = saved[1]
        for obj in set(bpy.data.objects) - objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        restore_points(port, saved[2])
        port.refresh(saved[3])


def saved_points(port):
    return {fiber.id: persisted_fiber_points(port.scene, port.root.name, fiber.id) for fiber in port.root.af_vcp_system.fibers}


def memento(port, previous):
    return (native_records(port.root), port.root.get("af_authoring_documents", "{}"), saved_points(port),
            (previous or {}).get("native_ids",{}))


def restore_points(port, points):
    sync = register_fiber_sync()
    for fiber in port.root.af_vcp_system.fibers:
        if points.get(fiber.id):
            sync.apply_points(port.root, port.scene, fiber, points[fiber.id], commit=True)

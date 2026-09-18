"""Anatomical scene facade, keeping RNA behind an application port."""
from pathlib import Path
from contextlib import contextmanager
import bpy
from . import inventory
from .native_scene import BlenderScene
from ...core.authoring.model import MeshSnapshot, SceneSnapshot, readonly


class StaticScene(BlenderScene):
    def remember_journal(self, directory):
        self.root['af_authoring_journal'] = str(directory)

    def capture_authoring(self):
        return inventory.capture(self.root, self.scene)

    def profile_inspect(self, target):
        from .native_profiles import inspect
        return inspect(self, target)

    def profile_preview(self, target, configuration):
        from .native_profiles import preview
        return preview(self, target, configuration)

    def profile_mutation(self, target, configuration, create=False, name=""):
        from .native_profiles import mutation
        return mutation(self, target, configuration, create, name)

    def profile_marker(self, muscle_id, kind, receipt=None):
        from .native_profiles import marker
        return marker(self, muscle_id, kind, receipt)

    def profile_recover_marker(self, request_id, kind):
        from .native_profiles import recover_marker
        return recover_marker(self, request_id, kind)

    def transfer_sources(self, names):
        from .transfer import capture
        return capture(self.scene, names)

    def publish_transfer(self, record):
        from .transfer import publish
        return publish(self.root, self.scene, record)

    def base_mesh_quality(self, vertices, triangles):
        from .base_quality import inspect
        return inspect(vertices, triangles)

    def publish_native_base(self, plan):
        from .base_native import publish
        return publish(self.root, self.scene, plan)

    def verify_native_base(self, receipt):
        from .base_native import verify
        return verify(self.root, self.scene, receipt)

    def base_candidates(self, source, supports):
        from .base_evidence import candidates
        return candidates(source, supports)

    def union_volume(self, sources):
        from .volume_union import evaluate
        return evaluate(self.scene, sources)

    def snap_points(self, params, captured):
        from .point_picker import snap_points
        return snap_points(self.root, self.scene, params, captured)

    def snap_binding(self, owner, point):
        from .attachments import snap_binding
        return snap_binding(self.root, self.scene, owner, point)

    def initialize(self):
        return inventory.initialize(self.root, self.scene)

    def capture(self, scene_id):
        data = self.capture_authoring()
        meshes = tuple(mesh(row, data) for row in data['instances'] if row['has_surface'])
        return SceneSnapshot(scene_id, data['revision'], meshes, data['reference_pose'])

    @contextmanager
    def publish(self, captured, document, outputs, previous):
        old_names = rescope(self.root, self.scene)
        try:
            with super().publish(captured, document, outputs, previous) as ids:
                stamp_proxies(self.root, self.scene)
                yield ids
        except BaseException:
            for obj, name in old_names:
                obj['af_root_name'] = name
            raise

    def save_copy(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True, check_existing=False)

    def save_debug_copy(self, path):
        from .presentation import prepare_debug_presentation
        prepare_debug_presentation(self.root, self.scene)
        self.save_copy(path)

    def save_checkpoint(self, path, generation):
        from ...core.authoring.codec import encode
        previous = self.root.get('af_authoring_generation')
        self.root['af_authoring_generation'] = encode(generation)
        try:
            self.save_copy(path)
        finally:
            if previous is None:
                del self.root['af_authoring_generation']
            else:
                self.root['af_authoring_generation'] = previous

    def native_changes(self, published):
        from .native_scene import root_documents, ownership
        saved = root_documents(self.root)[published['document']['document_id']]
        current = ownership(self.root, published['native_ids'])
        return dict(baseline=published.get('native_baseline', {}), current=self.owned_records(published['native_ids']), changed=current != saved['fingerprint'])

    def attachment_points(self, fiber):
        from .attachments import resolve_rows
        return resolve_rows(self.root, self.scene, fiber)

    def owned_records(self, ids):
        from .native_scene import grouped
        from .records import record
        groups = grouped(ids)
        return {k: {v.id: record(v) for v in getattr(self.root.af_vcp_system, k) if v.id in members} for k, members in groups.items()}

    def apply_overrides(self, rows):
        from .records import restore
        from .native import find
        from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates
        with suppress_vcp_prop_updates():
            for group, entries in rows.items():
                for identity, value in entries.items():
                    item = find(getattr(self.root.af_vcp_system, group), identity)
                    if item is not None:
                        restore(item, value)
        self.refresh()

    def authorize_restore(self, identity):
        from .native_scene import root_documents, ownership
        from ...core.authoring.codec import encode
        rows = root_documents(self.root)
        rows[identity]['fingerprint'] = ownership(self.root, rows[identity]['ids'])
        self.root['af_authoring_documents'] = encode(rows)

    @contextmanager
    def restoration(self, identity):
        previous = self.root.get('af_authoring_documents', '{}')
        try:
            self.authorize_restore(identity)
            yield
        except BaseException:
            self.root['af_authoring_documents'] = previous
            raise


def mesh(row, inventory_data):
    key = row['instance_id'] or row['locator']
    value = inventory_data['geometry'][key]
    return MeshSnapshot(key, readonly(value['vertices']), readonly(value['triangles'], int), readonly(value['matrix']), row['concept'], row['side'], row['label'])


def rescope(root, scene):
    identity = root.get('af_authoring_id')
    rows = [(o, o.get('af_root_name', '')) for o in scene.objects if identity and o.get('af_authoring_root_id') == identity and o.get('af_root_name') != root.name]
    for obj, _ in rows:
        obj['af_root_name'] = root.name
    return rows


def stamp_proxies(root, scene):
    for obj in scene.objects:
        if obj.get('af_root_name') == root.name and any(obj.get(key) for key in ('af_fiber_proxy', 'af_muscle_id', 'af_fiber_surface_id')):
            obj['af_authoring_root_id'] = root['af_authoring_id']

from .adapters import build_runtime_graph
from .drivers import DependencyDriver
from ..constraints.scp_constraints import evaluate_scp_constraints_runtime, apply_scp_input_write
from ..visualization.sync import register_sync
from ..visualization.fiber_sync import register_fiber_sync
from ..visualization.muscle_sync import register_muscle_sync
from ..visualization.blob_sync import register_blob_sync
from ..visualization.mirror_sync import register_mirror_sync


def _has_self_loop(adjacency, node):
    return node in adjacency.get(node, set())


class RuntimeGraphDriver(DependencyDriver):
    name = "runtime_graph_driver"

    def entity_types(self):
        return ("SCP", "FIBER", "MUSCLE", "BLOB")

    def build_graph(self, root, graph, entity_sets):
        built = build_runtime_graph(root, graph)
        for et, ids in built.items():
            entity_sets.setdefault(et, set()).update(set(ids or set()))


class SCPConstraintDriver(DependencyDriver):
    name = "scp_constraint_driver"

    def __init__(self):
        self._delayed_writes = {}

    def entity_types(self):
        return ("SCP",)

    def _apply_delayed_queue(self, root):
        if not self._delayed_writes:
            return set()
        changed_scps = set()
        for (etype, eid, port), value in list(self._delayed_writes.items()):
            if etype == "SCP":
                if apply_scp_input_write(root, eid, port, value):
                    changed_scps.add(eid)
        self._delayed_writes.clear()
        return changed_scps

    def inject_delayed_dirty(self, root, dirty):
        if "SCP" not in dirty:
            return set()
        changed = self._apply_delayed_queue(root)
        dirty["SCP"] |= changed
        return changed

    def apply_constraints(self, ctx):
        scp_all = set(ctx.entity_sets.get("SCP", set()) or set())
        scp_dirty = set(ctx.dirty.get("SCP", set()) or set())
        changed_source_scps = scp_all if ctx.is_full else scp_dirty
        if not changed_source_scps:
            return {}

        new_delayed = {}

        def delayed_writer(etype, eid, port, value):
            new_delayed[(etype, eid, port)] = value

        def is_cyclic_pair(src_id, dst_id):
            src_node = ("SCP", src_id)
            dst_node = ("SCP", dst_id)
            if src_node not in ctx.scc_idx or dst_node not in ctx.scc_idx:
                return False
            if ctx.scc_idx[src_node] != ctx.scc_idx[dst_node]:
                return False
            size = ctx.scc_sizes.get(ctx.scc_idx[src_node], 1)
            return size > 1 or _has_self_loop(ctx.adjacency, src_node)

        changed_dest_scps = evaluate_scp_constraints_runtime(
            root=ctx.root,
            changed_source_ids=changed_source_scps,
            is_cyclic_pair=is_cyclic_pair,
            delayed_writer=delayed_writer,
        )
        self._delayed_writes.clear()
        self._delayed_writes.update(new_delayed)
        return {"SCP": set(changed_dest_scps)}


class SCPSyncDriver(DependencyDriver):
    name = "scp_sync_driver"

    def entity_types(self):
        return ("SCP",)

    def sync(self, root, scene, is_full, impacted, bake):
        ids = set(impacted.get("SCP", set()) or set())
        if is_full:
            register_sync().sync_root_to_scene(root=root, scene=scene)
        elif ids:
            register_sync().sync_root_to_scene(root=root, scene=scene, target_scp_ids=ids)


class FiberSyncDriver(DependencyDriver):
    name = "fiber_sync_driver"

    def entity_types(self):
        return ("FIBER",)

    def sync(self, root, scene, is_full, impacted, bake):
        ids = set(impacted.get("FIBER", set()) or set())
        if is_full:
            register_fiber_sync().sync_root_to_scene(root=root, scene=scene, bake=bake)
        elif ids:
            register_fiber_sync().sync_root_to_scene(root=root, scene=scene, bake=bake, target_fiber_ids=ids)


class MuscleSyncDriver(DependencyDriver):
    name = "muscle_sync_driver"

    def entity_types(self):
        return ("MUSCLE",)

    def sync(self, root, scene, is_full, impacted, bake):
        ids = set(impacted.get("MUSCLE", set()) or set())
        if is_full:
            register_muscle_sync().sync_root_to_scene(root=root, scene=scene)
        elif ids:
            register_muscle_sync().sync_root_to_scene(root=root, scene=scene, target_muscle_ids=ids)


class BlobSyncDriver(DependencyDriver):
    name = "blob_sync_driver"

    def entity_types(self):
        return ("BLOB",)

    def sync(self, root, scene, is_full, impacted, bake):
        ids = set(impacted.get("BLOB", set()) or set())
        if is_full:
            register_blob_sync().sync_root_to_scene(root=root, scene=scene)
        elif ids:
            register_blob_sync().sync_root_to_scene(root=root, scene=scene, target_blob_ids=ids)


class MirrorPostSyncDriver(DependencyDriver):
    name = "mirror_post_sync_driver"

    def post_sync(self, root, scene, is_full, impacted, bake):
        register_mirror_sync().sync_root_to_scene(root=root, scene=scene)

import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import bpy
import numpy as np
from _helpers import BlenderTestCase, root
from adapters.draft_skin.vendor import ensure_worker_dependencies
ensure_worker_dependencies()
from adapters.warm_update import output, migration
from adapters.warm_update.current_output import current_skin_result, current_topology_result
from adapters.topology import warm
from core.warm_start.strategy_model import TopologyUpdateStopped
from core.topology.protocol import write_result, read_result
from workers import warm_update_array, warm_update_worker
from test_warm_update_integration import _skin_result, _topology_result, _skin_capture, _topology_capture, _points


def bound_scene():
    owner = root()
    skin, topology = output.replace_outputs(bpy.context.scene, owner, _skin_result(0), _topology_result(0))
    bound_skin = migration.prepare_skin(owner, bpy.context.scene, _skin_capture())
    bound_topology = migration.prepare_topology(owner, bpy.context.scene, _topology_capture())
    output.replace_outputs(bpy.context.scene, owner, bound_skin, bound_topology)
    return owner, skin, topology


def spec(folder, policy="STOP"):
    return SimpleNamespace(job_dir=str(folder), status_path=str(Path(folder) / "status.json"),
        cancel_path=str(Path(folder) / "cancel.request"), topology_update={"failure_policy": policy})


class TopologyStrategyIntegrationTests(BlenderTestCase):
    def test_both_workers_produce_identical_warm_update(self):
        owner, skin, _topology = bound_scene()
        before, old = current_skin_result(owner, bpy.context.scene), current_topology_result(owner, bpy.context.scene)
        after = replace(before, vertices=before.vertices + (.05, .05, .05))
        capture = replace(_topology_capture(), vertices=after.vertices, triangles=after.triangles)
        decision = SimpleNamespace(topology_rebuild=False)
        with tempfile.TemporaryDirectory() as folder:
            output.replace_outputs(bpy.context.scene, owner, after)
            after = current_skin_result(owner, bpy.context.scene)
            first = warm_update_array._solve_topology(spec(folder), capture, after, old, decision, "warm", before)[0]
            second = warm_update_worker._try_warm_topology(owner, bpy.context.scene, None,
                                                           "warm", spec(folder), capture, before)
        np.testing.assert_array_equal(first.vertices, second.vertices)
        np.testing.assert_array_equal(first.quads, old.quads)

    def test_direct_adapter_preserves_vertex_attributes(self):
        owner, skin, topology = bound_scene()
        before = current_skin_result(owner, bpy.context.scene)
        attribute = topology.data.attributes.new("test_identity", "INT", "POINT")
        attribute.data.foreach_set("value", np.arange(len(topology.data.vertices), dtype=np.int32))
        moved = replace(before, vertices=before.vertices + (.05, .05, .05))
        output.replace_outputs(bpy.context.scene, owner, moved)
        result = warm.update_topology(owner, bpy.context.scene, None, _topology_capture(), {"failure_policy": "STOP"}, before)
        self.assertTrue(result[1].valid)
        self.assertEqual([x.value for x in topology.data.attributes["test_identity"].data], list(range(8)))

    def test_stop_policy_leaves_scene_and_output_files_untouched(self):
        owner, skin, topology = bound_scene()
        before, old = current_skin_result(owner, bpy.context.scene), current_topology_result(owner, bpy.context.scene)
        positions = _points(topology).copy(); invalid = replace(old, vertices=old.vertices * np.nan)
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(warm_update_array, "_full_topology", side_effect=AssertionError("Rebuild forbidden")):
                with self.assertRaises(TopologyUpdateStopped):
                    warm_update_array._solve_topology(spec(folder), _topology_capture(), before, invalid,
                                                       SimpleNamespace(topology_rebuild=False), "rebuilt", before)
            self.assertFalse((Path(folder) / "topology_result.npz").exists())
        np.testing.assert_array_equal(_points(topology), positions)
        np.testing.assert_array_equal(_points(skin), before.vertices)

    def test_strategy_metadata_survives_result_serialization(self):
        owner, _skin, _topology = bound_scene()
        before, old = current_skin_result(owner, bpy.context.scene), current_topology_result(owner, bpy.context.scene)
        with tempfile.TemporaryDirectory() as folder:
            result = warm_update_array._solve_topology(spec(folder), _topology_capture(), before, old,
                SimpleNamespace(topology_rebuild=False), "warm", before)[0]
            write_result(Path(folder) / "result.npz", result)
            reopened = read_result(Path(folder) / "result.npz")
        self.assertEqual(reopened.statistics["topology_strategy"]["name"], "current")
        self.assertEqual(reopened.statistics["topology_strategy"]["failure_policy"], "STOP")

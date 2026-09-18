"""R4: main configuration transactions own selected-child control initialization."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import bpy
import numpy as np
from _helpers import BlenderTestCase
from _branch_fixture import create_fixture
from test_authoring_native_profiles import call, fail_response
from test_authoring_profile_review import configure_request, control_state
from anthroforge.adapters.authoring.capture import native_records
from anthroforge.adapters.authoring.records import record
from anthroforge.core.authoring.storage import FileStore
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.visualization import muscle_numeric_runtime as runtime
from anthroforge.core.visualization.muscle_profile_publish import affected_objects
from anthroforge.core.visualization.muscle_sync import register_muscle_sync


def selected_branch():
    owner, muscle, connection, _ = create_fixture()
    with suppress_vcp_prop_updates():
        owner.af_vcp_system.active_vcp_type = 'MUSCLE'
        owner.af_vcp_system.active_vcp_id = muscle.id
    register_muscle_sync().sync_root_to_scene(owner, bpy.context.scene)
    return owner, muscle, connection


def output_state(owner, muscle):
    result = {}
    for obj in affected_objects(owner, bpy.context.scene, muscle.id):
        geometry = ([tuple(v.co) for v in obj.data.vertices], [tuple(p.vertices) for p in obj.data.polygons]) if obj.type == 'MESH' else None
        result[obj.name] = (geometry, obj.id_properties_ensure().to_dict(), control_state(obj))
    return result


def journal_state(directory):
    folder = Path(directory)
    return {str(path.relative_to(folder)): path.read_bytes() for path in folder.rglob('*') if path.is_file()}


class ProfileBranchRollbackTests(BlenderTestCase):
    def setUp(self):
        super().setUp()
        self.owner, self.muscle, self.connection = selected_branch()
        directory = TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.directory = directory.name
        payload = self._request('previous', 'distributed')
        self.assertTrue(call(self.owner, self.directory, payload)['published'])
        with suppress_vcp_prop_updates():
            self.connection.settings.inflation_mode = 'CTRL_POINT'
            self.connection.settings.inflation_ctrl_world = (0., 0., 0.)
            self.connection.settings.inflation_ctrl_initialized = False

    def _request(self, identity, mode='control_point'):
        return configure_request(self.owner, self.directory, self.muscle, dict(mode=mode), identity)

    def _state(self):
        return (native_records(self.owner), output_state(self.owner, self.muscle),
                journal_state(self.directory), self.owner.get('af_authoring_journal'))

    def test_failed_main_journal_restores_main_child_outputs_and_previous_receipts(self):
        payload = self._request('failed-main')
        before, child = self._state(), record(self.connection.settings)
        with patch.object(runtime, '_store_initial_control', wraps=runtime._store_initial_control) as initialize:
            with patch.object(FileStore, 'put', fail_response(FileStore.put)):
                response = call(self.owner, self.directory, payload)
        self.assertEqual(response['status'], 'failed', response)
        self.assertEqual(initialize.call_count, 1)
        self.assertEqual(initialize.call_args.args[0], self.connection.settings)
        self.assertEqual(record(self.connection.settings), child)
        self.assertEqual(self._state(), before)

    def test_successful_main_configuration_retains_child_initialization_and_replays(self):
        payload = self._request('successful-main')
        child = self.connection.settings
        grid = runtime._branched_request(self.owner, bpy.context.scene, self.muscle).assembly.branches[0].grid
        response = call(self.owner, self.directory, payload)
        self.assertTrue(response['published'], response)
        self.assertTrue(child.inflation_ctrl_initialized)
        np.testing.assert_array_equal(child.inflation_ctrl_world, np.float32(grid[len(grid)//2, len(grid[0])//2]))
        self.assertEqual(self.muscle.inflation_mode, 'CTRL_POINT')
        before = self._state()
        replay = call(self.owner, self.directory, payload)
        self.assertTrue(replay['replayed'], replay)
        self.assertEqual(self._state()[:2], before[:2])

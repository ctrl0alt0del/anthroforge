"""Durable placement survives package extraction without load hydration."""

from pathlib import Path
from tempfile import TemporaryDirectory

import bpy
import numpy as np

from _helpers import BlenderTestCase, reset_scene, root
from test_import_package_e2e import _source_snapshot
from anthroforge.core.importing.extract import root_snapshot
from anthroforge.core.importing.service import import_package_from_blend
from anthroforge.core.vcp.muscle_inflation_state import (INITIALIZED_KEY, LEGACY_KEY,
    WORLD_KEY, inflation_control_initialized, inflation_control_world)
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates


def _source(state):
    _source_snapshot()
    muscle = root().af_vcp_system.muscles[0]
    with suppress_vcp_prop_updates():
        for key in (INITIALIZED_KEY, LEGACY_KEY, WORLD_KEY):
            if key in muscle:
                del muscle[key]
        for key, value in state.items():
            if key == LEGACY_KEY: muscle[key] = value
            else: setattr(muscle, key, value)
    return muscle


def _assert_placement(test, muscle, point, initialized):
    np.testing.assert_allclose(inflation_control_world(muscle), point, atol=1e-7, rtol=0)
    test.assertEqual(inflation_control_initialized(muscle), initialized)


def _package_roundtrip(test, state, point, initialized):
    _source(state)
    with TemporaryDirectory(prefix="af11-package-") as directory:
        path = str(Path(directory) / "package.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path)
        reset_scene()
        result = import_package_from_blend(path, bpy.context)
        test.assertEqual(result.muscle_count, 1)
        _assert_placement(test, root().af_vcp_system.muscles[0], point, initialized)


class MuscleInflationImportTests(BlenderTestCase):
    def test_snapshot_migrates_legacy_without_hydration(self):
        muscle = _source({LEGACY_KEY: (1.3, 2.1, -0.03)})
        self.assertNotIn(INITIALIZED_KEY, muscle)
        props = root_snapshot(root()).muscles[0].props
        self.assertTrue(props[INITIALIZED_KEY])
        np.testing.assert_allclose(props[WORLD_KEY], (1.3, 2.1, -0.03), atol=1e-7, rtol=0)

    def test_package_preserves_authored_origin(self):
        state = {WORLD_KEY: (0, 0, 0), INITIALIZED_KEY: True}
        _package_roundtrip(self, state, (0, 0, 0), True)

    def test_package_migrates_present_legacy_origin(self):
        _package_roundtrip(self, {LEGACY_KEY: (0, 0, 0)}, (0, 0, 0), True)

    def test_package_migrates_present_legacy_offcentre(self):
        _package_roundtrip(self, {LEGACY_KEY: (1.3, 2.1, -0.03)}, (1.3, 2.1, -0.03), True)

    def test_package_preserves_false_marker_over_legacy(self):
        state = {WORLD_KEY: (1, 2, 3), INITIALIZED_KEY: False, LEGACY_KEY: (8, 9, 10)}
        _package_roundtrip(self, state, (1, 2, 3), False)

    def test_package_absent_control_remains_uninitialized_in_distributed_mode(self):
        _package_roundtrip(self, {}, (0, 0, 0), False)

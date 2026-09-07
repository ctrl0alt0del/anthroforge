import unittest
from types import SimpleNamespace

from core.vcp.muscle_inflation_state import (INITIALIZED_KEY, LEGACY_KEY, WORLD_KEY,
    inflation_control_initialized, inflation_control_world, migrate_inflation_control,
    set_inflation_control_world)
from core.vcp.runtime_state import reset_muscle_runtime


class MuscleInflationStateTests(unittest.TestCase):
    def test_namespace_runtime_adapter_can_store_new_placement(self):
        muscle = SimpleNamespace()
        set_inflation_control_world(muscle, (1, 2, 3))
        self.assertTrue(inflation_control_initialized(muscle))
        self.assertEqual(inflation_control_world(muscle), (1, 2, 3))

    def test_absent_control_stays_uninitialized(self):
        muscle = {}
        self.assertFalse(inflation_control_initialized(muscle))
        self.assertEqual(inflation_control_world(muscle), (0.0, 0.0, 0.0))
        self.assertEqual(muscle, {})

    def test_present_legacy_origin_is_initialized(self):
        muscle = {LEGACY_KEY: [0.0, 0.0, 0.0]}
        self.assertTrue(migrate_inflation_control(muscle))
        self.assertEqual(muscle[WORLD_KEY], (0.0, 0.0, 0.0))

    def test_legacy_offcentre_migration_is_idempotent(self):
        muscle = {LEGACY_KEY: [0.7, -1.4, 0.25]}
        self.assertEqual(inflation_control_world(muscle), (0.7, -1.4, 0.25))
        muscle[LEGACY_KEY] = [7.0, 8.0, 9.0]
        self.assertTrue(migrate_inflation_control(muscle))
        self.assertEqual(inflation_control_world(muscle), (0.7, -1.4, 0.25))

    def test_explicit_false_marker_overrides_legacy(self):
        muscle = {INITIALIZED_KEY: False, WORLD_KEY: (1, 2, 3), LEGACY_KEY: (4, 5, 6)}
        self.assertFalse(migrate_inflation_control(muscle))
        self.assertEqual(inflation_control_world(muscle), (1, 2, 3))

    def test_saved_origin_survives_runtime_reset(self):
        muscle = {LEGACY_KEY: (1, 2, 3)}
        set_inflation_control_world(muscle, (0, 0, 0))
        reset_muscle_runtime(muscle)
        self.assertTrue(inflation_control_initialized(muscle))
        self.assertEqual(inflation_control_world(muscle), (0, 0, 0))

    def test_saved_offcentre_survives_runtime_reset(self):
        muscle = {}
        set_inflation_control_world(muscle, (0.7, -1.4, 0.25))
        reset_muscle_runtime(muscle)
        self.assertEqual(inflation_control_world(muscle), (0.7, -1.4, 0.25))

    def test_invalid_legacy_value_does_not_initialize(self):
        for value in (None, (), [1, 2], [1, 2, 3, 4], [0, float("nan"), 1], "bad"):
            with self.subTest(value=value):
                self.assertFalse(migrate_inflation_control({LEGACY_KEY: value}))

    def test_invalid_authored_value_does_not_overwrite_placement(self):
        muscle = {}
        set_inflation_control_world(muscle, (1, 2, 3))
        with self.assertRaises(ValueError):
            set_inflation_control_world(muscle, (0, float("inf"), 0))
        self.assertEqual(inflation_control_world(muscle), (1, 2, 3))

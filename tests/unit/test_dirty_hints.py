import unittest
from unittest.mock import patch

from core.deps.dirty_hints import dirty_hints_for


class DirtyHintsTests(unittest.TestCase):
    def test_target_survives_before_driver_registration(self):
        with patch("core.deps.dirty_hints.get_registered_entity_types", return_value=()):
            hints = dirty_hints_for("SCP", {"SCP_4"})
        self.assertEqual(hints, {"SCP": {"SCP_4"}})
        self.assertFalse(hints.full)

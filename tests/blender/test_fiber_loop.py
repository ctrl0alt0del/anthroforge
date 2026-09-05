from pathlib import Path
import sys
import unittest

from mathutils import Vector

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT.parent)):
    if value not in sys.path:
        sys.path.insert(0, value)

from anthroforge.core.vcp.fiber_loop import resample_closed


class FiberLoopTests(unittest.TestCase):
    def test_resample_closed_preserves_count_and_uniform_spacing(self):
        source = [Vector(row) for row in ((0, 0, 0), (2, 0, 0), (2, 1, 0), (0, 1, 0))]
        points = resample_closed(source, 12)
        lengths = [(points[(i + 1) % len(points)] - point).length for i, point in enumerate(points)]
        self.assertEqual(len(points), 12)
        self.assertLess(max(lengths) - min(lengths), 1.0e-9)


if __name__ == "__main__":
    unittest.main(argv=[__file__])

from pathlib import Path
import sys
import unittest

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from _support import ensure_import_path, install_fake_modules

ensure_import_path()
install_fake_modules()

from core.vcp.fiber_symmetry import expand_mirror_seam_points


class FiberSymmetryTests(unittest.TestCase):
    def test_mirrors_all_points_when_half_loop_is_off_plane(self):
        result = expand_mirror_seam_points([(1, 0, 0), (2, 0, 0), (3, 0, 0)], "X", (0, 0, 0))
        self.assertEqual([tuple(point) for point in result], [(1, 0, 0), (2, 0, 0), (3, 0, 0), (-3, 0, 0), (-2, 0, 0), (-1, 0, 0)])

    def test_mirrors_only_interior_when_endpoints_are_on_plane(self):
        result = expand_mirror_seam_points([(0, 0, 0), (2, 0, 0), (0, 1, 0)], "X", (0, 0, 0))
        self.assertEqual([tuple(point) for point in result], [(0, 0, 0), (2, 0, 0), (0, 1, 0), (-2, 0, 0)])


if __name__ == "__main__":
    unittest.main()

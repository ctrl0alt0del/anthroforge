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

from core.scp_runtime.surface import _closest_point_barycentric


class Vec:
    def __init__(self, x, y, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)

    def __sub__(self, other):
        return Vec(self.x - other.x, self.y - other.y, self.z - other.z)

    def dot(self, other):
        return (self.x * other.x) + (self.y * other.y) + (self.z * other.z)


class SurfaceCaptureTests(unittest.TestCase):
    def test_barycentric_returns_vertex_weight_for_exact_hit(self):
        a = Vec(0.0, 0.0)
        b = Vec(1.0e-3, 0.0)
        c = Vec(0.0, 1.0e-3)
        self.assertEqual(_closest_point_barycentric(a, b, c, b), (0.0, 1.0, 0.0))

    def test_barycentric_accepts_thin_triangle_with_relative_tolerance(self):
        a = Vec(0.0, 0.0)
        b = Vec(1.0e-3, 0.0)
        c = Vec(0.0, 1.0e-3)
        weights = _closest_point_barycentric(a, b, c, Vec(2.5e-4, 2.5e-4))
        self.assertEqual(tuple(round(value, 4) for value in weights), (0.5, 0.25, 0.25))

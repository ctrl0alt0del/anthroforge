"""Numerical and protocol regressions for the authoring interpreter."""
import ast
import json
import unittest
from copy import deepcopy
from pathlib import Path
import numpy as np
from core.authoring import codec, schema, validation, inflation, contact
from core.authoring.errors import AuthoringError
from core.authoring.patching import apply_patch
from core.authoring.regions import RegionResolver
from core.authoring.model import MeshSnapshot, SceneSnapshot, FiberPlan, Anchor
from core.authoring.compilation import material_coordinates, material_samples
from core.authoring.nearest import nearest

ROOT = Path(__file__).resolve().parents[2]


def fixture():
    return json.loads((ROOT / "tests/fixtures/authoring/02-upper-arm.json").read_text())


def cube(identity="SCP_DEMO_origin"):
    vertices = np.array([(0,0,0),(1,0,0),(1,1,0),(0,1,0),(0,0,1),(1,0,1),(1,1,1),(0,1,1)], float)
    faces = np.array([(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),
                      (1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)])
    return MeshSnapshot(identity, vertices, faces, np.eye(4))


class AuthoringCoreTests(unittest.TestCase):
    def test_native_material_accepts_different_node_counts(self):
        from core.authoring.runtime import surface
        rows = [[[0,0,0],[0,0,1]], [[1,0,0],[1,0,.4],[1,0,1]]]
        material = dict(u=[0,1],s=[0,.25,.5,.75,1],row_s=[[0,1],[0,.4,1]],closed=False)
        result = surface(rows,codec.encode(material))
        self.assertEqual(len(result.vertices),85)

    def test_all_schema_examples(self):
        for path in (ROOT / "tests/fixtures/authoring").glob("*.json"):
            value = codec.decode(path.read_text())
            schema.validate(value, "protocol" if value.get("message_type") else "authoring")
            if not value.get("message_type"):
                validation.document(value)

    def test_reject_duplicate_and_nonfinite_json(self):
        for text in ('{"a":1,"a":2}', '{"a":1e999}', '[NaN]', '[Infinity]'):
            with self.subTest(text=text), self.assertRaises(AuthoringError):
                codec.decode(text)

    def test_unknown_fields_and_bool_numbers(self):
        for key, value in (("revision", True), ("unknown", 3)):
            document = fixture()
            document[key] = value
            with self.assertRaises(AuthoringError):
                validation.document(document)

    def test_reject_wrong_binding(self):
        document = fixture()
        document["muscles"]["example_muscle"]["region_bindings"]["origin"]["region"] = "guide"
        with self.assertRaises(AuthoringError):
            validation.document(document)

    def test_patch_atomic_and_protected(self):
        document = fixture()
        original = deepcopy(document)
        operations = [dict(op="replace", path="/context/scope", value="changed"), dict(op="test", path="/revision", value=2)]
        with self.assertRaises(AuthoringError):
            apply_patch(document, operations)
        self.assertEqual(original, document)
        with self.assertRaises(AuthoringError):
            apply_patch(document, [dict(op="replace", path="/revision", value=2)])

    def test_region_projects_to_qualified_surface(self):
        document = fixture()
        snap = SceneSnapshot("scene", "revision", tuple(cube("SCP_DEMO_"+n) for n in document["targets"]))
        resolver = RegionResolver(document, snap)
        samples = resolver.resolve("origin")
        self.assertTrue(all(abs(row["point"][1]-1) < 1e-10 for row in samples))
        self.assertEqual(len(samples), 3)

    def test_station_coordinates_keep_native_vertices(self):
        points = np.array([(0,0,0),(0,0,2),(0,0,3),(0,0,4)])
        anchors = tuple(Anchor("owner", tuple(p), (0,1,0), tuple(p), 0) for p in points[[0,1,3]])
        plan = FiberPlan("fiber", 0, anchors, (0,.5,1), 4, False)
        values = material_coordinates(points, plan)
        np.testing.assert_allclose(values, [0,.5,.75,1])
        self.assertIn(.5, material_samples((0,.5,1), 64, False))

    def test_interior_contact_without_vertex_penetration(self):
        mesh = cube()
        tri = np.array([(-5,-5,.5),(5,-5,.5),(0,6,.5)], float)
        depth = contact.triangle_depth(tri, mesh.vertices[mesh.triangles], .001)
        self.assertGreater(depth, .1)

    def test_clearance_is_not_a_refinement_trigger(self):
        mesh = cube()
        vertices = np.array([(-1,-1,1.00001),(2,-1,1.00001),(2,2,1.00001),(-1,2,1.00001)])
        result = contact.evaluate(vertices, np.array([(0,1,2,3)]), SceneSnapshot("s","r",(mesh,)), .000001)
        self.assertEqual(result["area"], 0)

    def test_nearest_returns_surface(self):
        mesh = cube()
        point, _ = nearest(mesh.vertices[mesh.triangles], np.array([.5,.5,2]))
        np.testing.assert_allclose(point, [.5,.5,1])

    def test_material_volume_and_gaussian_tail(self):
        grid, u = inflation.loft([[(0,0,0),(0,0,1)],[(1,0,0),(1,0,1)]], [0,1])
        config = dict(enabled=True, mode="control_point", amount=.8, flip_normals=False, control=[.5,.5],
                      radius=.001, direction_depth=1, falloff="gaussian", boundary=dict(along=.1,across=.1,strength=1,power=1))
        result = inflation.inflate(grid, u, np.array([0,1]), config)
        np.testing.assert_allclose(result, grid)

    def test_function_size(self):
        paths = [p for folder in ("core/authoring","app/authoring","adapters/authoring") for p in (ROOT/folder).rglob("*.py")]
        for path in paths:
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.assertLessEqual(node.end_lineno-node.lineno+1, 15, f"{path}:{node.name}")

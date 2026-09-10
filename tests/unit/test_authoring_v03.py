"""Contracts introduced by the practical skeleton authoring review."""
import json
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from core.authoring import conformance, schema, validation, sheets, contact_repair, shape, extensions
from core.authoring.errors import AuthoringError


def fixture():
    document = json.loads((Path(__file__).parents[1]/"fixtures/authoring/02-upper-arm.json").read_text())
    document["version"] = "0.3.0"
    document["$schema"] = "../../../core/authoring/schemas/authoring-0.3.schema.json"
    construction = document["recipes"]["pattern"]["construction"]
    construction["boundary_conformance"] = dict(stations=[construction["stations"][0]["id"]],
        max_error=dict(value=.0001,unit="scene"),blend_span=.1,max_samples=257)
    return document


class AuthoringV03Tests(unittest.TestCase):
    def test_shipped_v03_examples(self):
        folder = Path(__file__).parents[1]/"fixtures/authoring_v03"
        for path in folder.glob("*.json"):
            value = json.loads(path.read_text())
            validation.request(value) if value.get("message_type") else validation.document(value)

    def test_projection_chart_gap_and_seam_rejected(self):
        spec = dict(charts=[dict(domain=[[0,.5]],direction_in_frame=[0,0,1])])
        with self.assertRaises(AuthoringError):
            sheets.specifications(spec,(.8,))
        with self.assertRaises(AuthoringError):
            sheets.joined([(np.zeros(3),np.array([0,0,1]),"a"),(np.ones(3),np.array([0,0,1]),"a")],.001)

    def test_surface_budget_fails_without_adding_fibers(self):
        document = fixture()
        document["recipes"]["pattern"]["construction"]["boundary_conformance"]["max_samples"] = 2
        with self.assertRaises(AuthoringError):
            conformance.samples(document,"example_muscle",CurvedResolver(),[0,1])

    def test_versioned_validation(self):
        document = fixture()
        validation.document(document)
        document["version"] = "0.2.0"
        with self.assertRaises(AuthoringError):
            validation.document(document)

    def test_curved_boundary_adds_real_fiber_plans(self):
        from core.authoring.compilation import fibers
        document = fixture()
        resolver = CurvedResolver()
        plans = fibers(document, 'example_muscle', resolver)
        u = np.array([plan.u for plan in plans])
        self.assertGreater(len(plans), 5)
        np.testing.assert_allclose([p.anchors[0].point[1] for p in plans], .2*np.sin(np.pi*u), atol=1e-10)
        self.assertEqual(document["recipes"]["pattern"]["construction"]["fiber_u"],[0,.25,.5,.75,1])

    def test_split_contact_patch_is_allowed(self):
        before = dict(material_triangles=[[[0,0],[1,0],[1,1]],[[0,0],[1,1],[0,1]]])
        after = dict(material_triangles=[[[.1,.1],[.2,.1],[.2,.2]],[[.7,.7],[.8,.7],[.8,.8]]])
        self.assertTrue(contact_repair.covered(before,after))
        after["material_triangles"][0][0] = [1.1,.2]
        self.assertFalse(contact_repair.covered(before,after))

    def test_explicit_sheet_selection_requires_separation(self):
        hits = [(1,0,np.array([0,0,.1])),(2,1,np.array([0,0,.3]))]
        spec = dict(hit_policy="closest_seed",selection_margin=dict(value=.01))
        self.assertEqual(sheets.select(hits,np.zeros(3),spec,CurvedResolver())[1],0)
        with self.assertRaises(AuthoringError):
            sheets.select(hits,np.array([0,0,.2]),spec,CurvedResolver())

    def test_landmarks_define_right_handed_frame(self):
        spec = dict(landmarks_q=dict(origin=[0,0,0],x=[0,1,0],xy=[0,1,1]))
        basis = extensions.landmark_basis(spec,np.array([[0,0,0],[2,3,4]]))
        np.testing.assert_allclose(basis[:,0],[0,1,0])
        self.assertAlmostEqual(np.linalg.det(basis),1)

    def test_width_detects_narrow_surface_despite_large_height(self):
        base = np.array([[[0,0,0],[0,0,1]],[[.1,0,0],[.1,0,1]]])
        inflated = base.copy(); inflated[:,:,1] = .81
        check = dict(metric="section_width",s=.5,u_range=[0,1],statistic="max")
        value = shape.measure(base,inflated,[0,1],[0,1],{},False,check)
        self.assertAlmostEqual(value,.1)


class CurvedResolver:
    def measure(self,spec):
        return spec.get("value",0)

    def point(self,name,at,offset):
        u = at[0]
        return SimpleNamespace(point=(u,.2*np.sin(np.pi*u),0))

    @property
    def document(self):
        return fixture()

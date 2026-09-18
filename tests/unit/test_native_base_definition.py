"""Whole-underside selection topology and explicit head contracts."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.authoring.base_definition import define
from core.authoring.errors import AuthoringError
from core.authoring.schema import validate

VERTICES = [[0, 0, 0], [1, 0, 0], [1, 2, 0], [0, 2, 0]]
FACES = [[0, 1, 2], [0, 2, 3]]
HEADS = [dict(id='head', label='Explicit anatomical head')]


def patch(**kwargs):
    return dict(dict(id='sheet', head_ids=['head'], source_triangles=[0, 1], boundary_vertex_ids=[0, 1, 2, 3]), **kwargs)


class NativeBaseDefinitionTests(unittest.TestCase):
    def test_indexed_disk_keeps_whole_surface(self):
        result = define(VERTICES, FACES, HEADS, [patch()])
        self.assertEqual(result['patches'][0]['triangles'], FACES)
        self.assertEqual(result['patches'][0]['topology']['boundary_components'], 1)

    def test_unknown_head_and_repeated_faces_rejected(self):
        for changes in (dict(head_ids=['unknown']), dict(source_triangles=[0, 0, 1]), dict(boundary_vertex_ids=[0, 2, 1, 3])):
            with self.assertRaises(AuthoringError):
                define(VERTICES, FACES, HEADS, [patch(**changes)])

    def test_overlapping_patch_selections_are_not_two_heads(self):
        with self.assertRaises(AuthoringError):
            define(VERTICES, FACES, HEADS, [patch(), patch(id='second')])

    def test_native_limit_is_eight_and_no_free_offset(self):
        binding = dict(role='origin', document_id='d', expected_draft_revision=1, region='/regions/r', across=[0, 1], max_distance=.1)
        params = dict(scene_id='s', expected_scene_revision='r', base_id='b', tolerance=.1,
                      parts=[dict(patch_id='p', bindings=[binding, dict(binding, role='insertion')])], max_middle_points=8)
        request = dict(version='0.4.0', message_type='request', request_id='r', op='anatomy.plan_base_fibers', params=params)
        validate(request, 'protocol'); params['max_middle_points'] = 9
        with self.assertRaises(AuthoringError):
            validate(request, 'protocol')
        params['max_middle_points'] = 8; binding['offset'] = .1
        with self.assertRaises(AuthoringError):
            validate(request, 'protocol')

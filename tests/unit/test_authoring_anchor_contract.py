"""Unsupported hard-anchor offsets fail before any native work."""
import unittest
from core.authoring import validation, lowering, anchor_contract
from core.authoring.errors import AuthoringError
from test_authoring_v04 import fixture, inventory


class AnchorContractTests(unittest.TestCase):
    def test_endpoint_offset_rejected_at_draft_validation(self):
        value = fixture()
        value['recipes']['pattern']['construction']['stations'][0]['offset']['value'] = .03
        with self.assertRaises(AuthoringError) as raised:
            validation.document(value)
        self.assertEqual(raised.exception.code, 'UNSUPPORTED_ANCHOR_OFFSET')
        self.assertEqual(raised.exception.pointer, '/recipes/pattern/construction/stations/0/offset')

    def test_omitted_offsets_default_to_zero(self):
        value = fixture()
        for station in value['recipes']['pattern']['construction']['stations']:
            del station['offset']
        validation.document(value)
        native = lowering.compile_document(value, inventory())['document']
        for recipe in native['recipes'].values():
            self.assertTrue(all(s['offset'] == dict(value=0, unit='scene') for s in recipe['construction']['stations']))

    def test_explicit_middle_offset_is_preserved(self):
        value = fixture()
        value['recipes']['pattern']['construction']['stations'][1]['offset']['value'] = .03
        validation.document(value)
        native = lowering.compile_document(value, inventory())['document']
        self.assertTrue(all(r['construction']['stations'][1]['offset']['value'] == .03 for r in native['recipes'].values()))

    def test_loop_offsets_rejected(self):
        build = dict(kind='closed_loft', loops=[dict(anchors=dict(first=dict(offset=dict(fraction=.03))))])
        with self.assertRaises(AuthoringError) as raised:
            anchor_contract.construction(build, '/recipe')
        self.assertEqual(raised.exception.pointer, '/recipe/loops/0/anchors/first/offset')

    def test_route_offset_rejected_in_assemblies(self):
        value = fixture()
        instance = next(iter(value['instances'].values()))
        region = next(iter(instance['bindings'].values()))
        rows = [dict(region=region, seed=[0, 0, 0], offset=n) for n in (.03, 0)]
        instance['route_overrides'] = dict(fiber=dict(anchors=rows, evidence=instance['evidence']))
        value['assemblies'] = dict(group=dict(instances=dict(muscle=instance), evidence=instance['evidence']))
        value['instances'] = {}
        with self.assertRaises(AuthoringError) as raised:
            validation.document(value)
        self.assertEqual(raised.exception.pointer, '/assemblies/group/instances/muscle/route_overrides/fiber/anchors/0/offset')

    def test_retained_route_binding_needs_no_seed_or_offset(self):
        value = fixture()
        instance = next(iter(value['instances'].values()))
        region = next(iter(instance['bindings'].values()))
        binding = dict(tri_vidx=[0, 1, 2], tri_weights=[1, 0, 0])
        rows = [dict(region=region, surface_binding=binding) for _ in range(2)]
        instance['route_overrides'] = dict(fiber=dict(anchors=rows, evidence=instance['evidence']))
        validation.document(value)

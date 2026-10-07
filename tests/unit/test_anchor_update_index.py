"""Callback-local indexes preserve anchor invalidation decisions and scope."""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[2])]
from _support import ensure_import_path, install_fake_modules
ensure_import_path()
install_fake_modules()
from core.visualization import fiber_cache_lifecycle as lifecycle


class Owner(dict):
    def __init__(self, data):
        super().__init__(af_scp_geometry=True)
        self.data = data


class Objects(list):
    scans = 0

    def __iter__(self):
        self.scans += 1
        return super().__iter__()


def update(item, geometry=True, transform=False):
    return NS(id=item, is_updated_geometry=geometry, is_updated_transform=transform)


class AnchorUpdateIndexTests(unittest.TestCase):
    def test_identity_is_preserved_for_equal_but_distinct_data(self):
        data, equal = NS(value=1), NS(value=1)
        scene = NS(objects=[Owner(data)]); index = lifecycle._anchor_geometry_data(scene)
        self.assertTrue(lifecycle._relevant_anchor_update(scene, update(data), index))
        self.assertFalse(lifecycle._relevant_anchor_update(scene, update(equal), index))

    def test_one_scene_scan_for_many_unrelated_updates(self):
        objects = Objects([Owner(object())]); scene = NS(objects=objects)
        graph = NS(updates=[update(object()) for _ in range(100)])
        with patch.object(lifecycle, '_invalidate_anchor_caches') as invalidate:
            lifecycle._invalidate_anchor_geometry(scene, graph)
        self.assertEqual(objects.scans, 1); invalidate.assert_not_called()

    def test_shading_only_or_empty_updates_do_not_scan(self):
        objects = Objects([Owner(object())]); scene = NS(objects=objects)
        for updates in ((), (update(objects[0].data, False),)):
            lifecycle._invalidate_anchor_geometry(scene, NS(updates=updates))
        self.assertEqual(objects.scans, 0)

    def test_shared_geometry_and_transform_changes_notify_once(self):
        data = object(); scene = NS(objects=[Owner(data), Owner(data)])
        graph = NS(updates=[update(data, False, True), update(data)])
        with patch.object(lifecycle, '_invalidate_anchor_caches') as invalidate, \
             patch.object(lifecycle, '_notify_warnings') as notify:
            lifecycle._invalidate_anchor_geometry(scene, graph)
        invalidate.assert_called_once_with(scene, None, None)
        notify.assert_called_once_with(scene, None)

    def test_replaced_geometry_is_seen_by_next_callback(self):
        old, new = object(), object(); owner = Owner(old); scene = NS(objects=[owner])
        with patch.object(lifecycle, '_invalidate_anchor_caches') as invalidate, patch.object(lifecycle, '_notify_warnings'):
            lifecycle._invalidate_anchor_geometry(scene, NS(updates=[update(old)]))
            owner.data = new
            lifecycle._invalidate_anchor_geometry(scene, NS(updates=[update(old)]))
            lifecycle._invalidate_anchor_geometry(scene, NS(updates=[update(new)]))
        self.assertEqual(invalidate.call_count, 2)

    def test_direct_geometry_tag_does_not_require_scene_membership(self):
        scene = NS(objects=[]); item = Owner(None)
        self.assertTrue(lifecycle._relevant_anchor_update(scene, update(item), {}))
        self.assertFalse(lifecycle._relevant_anchor_update(scene, update(item, False), {}))

    def test_none_data_keeps_original_identity_semantics(self):
        scene = NS(objects=[Owner(None)]); index = lifecycle._anchor_geometry_data(scene)
        self.assertTrue(lifecycle._relevant_anchor_update(scene, update(None), index))

    def test_untagged_data_is_not_an_anchor_dependency(self):
        owner = Owner(object()); owner['af_scp_geometry'] = False
        scene = NS(objects=[owner]); index = lifecycle._anchor_geometry_data(scene)
        self.assertFalse(lifecycle._relevant_anchor_update(scene, update(owner.data), index))

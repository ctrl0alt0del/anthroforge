"""Real-scene import regressions: shortcut proxies and Free material stations."""
import json
from dataclasses import replace
import numpy as np
import bpy
from _helpers import BlenderTestCase, add_shortcut
from _stacking_fixture import fixture
from test_import_package_e2e import _finish_import
from test_muscle_section_profile import mesh
from anthroforge.core.importing.extract import root_snapshot
from anthroforge.core.importing.vcp import apply_vcp_snapshot
from anthroforge.core.vcp.free_surface_stations import KEY, resolve
from anthroforge.core.vcp.free_path import decode
from anthroforge.core.visualization.sync_runner import sync_from_dirty_hints
from anthroforge.adapters.free_fiber_import import _capture, _restore


def stations(root):
    for surface in root.af_vcp_system.fiber_surfaces:
        rows = []
        for ref in surface.fiber_refs:
            fiber = next(f for f in root.af_vcp_system.fibers if f.id == ref.fiber_id)
            samples = decode(fiber.free_path_json)['samples']; count = len(samples)
            rows.append(dict(fiber_id=fiber.id, sample_ids=[s['sample_id'] for s in samples],
                stations=(np.linspace(0, 1, count)**1.4).tolist(), reference_points=[s['co'] for s in samples]))
        surface[KEY] = json.dumps(dict(version=1, rows=rows))
    sync_from_dirty_hints(root, bpy.context.scene, {'MUSCLE': {m.id for m in root.af_vcp_system.muscles}}, full=False)


class FullSceneImport(BlenderTestCase):
    def test_shortcut_rollback_does_not_evaluate_or_set_live_proxies(self):
        root, _, _ = fixture(); root['test_scalar'] = 2.5
        row = add_shortcut(root, 'Scalar', 'ROOT', '', f'bpy.data.objects["{root.name}"]["test_scalar"]')
        saved = _capture(root); root.af_shortcut_system.shortcuts.clear(); _restore(root, saved)
        self.assertEqual(root['test_scalar'], 2.5)
        self.assertEqual(root.af_shortcut_system.shortcuts[0].name, 'Scalar')
        self.assertFalse(any(k.startswith('proxy_') for k in saved['shortcuts'][0]['values']))

    def test_import_preserves_material_grid_with_remapped_fiber_ids(self):
        root, lower, cover = fixture(); stations(root); _finish_import()
        expected = [mesh(root, m, 'BASE') for m in (lower, cover)]; snapshot = root_snapshot(root)
        result = apply_vcp_snapshot(snapshot, root, bpy.context); _finish_import()
        sync_from_dirty_hints(root, bpy.context.scene, {'MUSCLE': {m.id for m in root.af_vcp_system.muscles}}, full=False)
        self.assertEqual(result.muscle_count, 2); self.assertFalse(result.warnings)
        for target, actual in zip(expected, root.af_vcp_system.muscles[-2:]):
            np.testing.assert_allclose(target, mesh(root, actual, 'BASE'), atol=2e-6)
        for surface in root.af_vcp_system.fiber_surfaces[-2:]:
            fibers = [next(f for f in root.af_vcp_system.fibers if f.id == r.fiber_id) for r in surface.fiber_refs]
            self.assertTrue(resolve(surface, fibers))
            self.assertTrue(all(f.id not in snapshot.fiber_surfaces[0].fiber_ids for f in fibers))

    def test_invalid_material_stations_rejected_before_mutation(self):
        root, _, _ = fixture(); stations(root); snapshot = root_snapshot(root)
        bad = json.loads(snapshot.fiber_surfaces[0].material_stations); bad['rows'][0]['stations'][1] = -1
        snapshot.fiber_surfaces[0].material_stations = json.dumps(bad)
        counts = len(root.af_vcp_system.fibers), len(root.af_vcp_system.muscles)
        with self.assertRaisesRegex(ValueError, 'FREE_IMPORT_CORRESPONDENCE_STATIONS'):
            apply_vcp_snapshot(snapshot, root, bpy.context)
        self.assertEqual(counts, (len(root.af_vcp_system.fibers), len(root.af_vcp_system.muscles)))

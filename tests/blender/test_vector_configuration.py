"""Vector settings migrate without changing saved numeric choices or intent."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import bpy
from _helpers import BlenderTestCase
from _stacking_fixture import fixture
from test_muscle_stacking import refresh, call
from anthroforge.core.muscle_pairs import configuration


class VectorConfiguration(BlenderTestCase):
    def test_old_settings_preserved_and_new_defaults_persist(self):
        root, _, _ = fixture(); name = root.name
        root[configuration.KEY] = json.dumps(dict(stacking=False, smoothing_radius=.27, smoothing_strength=.6, clearance=.02, displacement=.13))
        values = configuration.read(root)
        self.assertEqual([values[k] for k in ('smoothing_radius', 'smoothing_strength', 'clearance', 'displacement')], [.27, .6, .02, .13])
        self.assertEqual([values[k] for k in ('blend_distance', 'preservation_weight', 'smoothing_max_adjustment')], [1., 100., 4.])
        root.af_pair_settings.blend = .7; root.af_pair_settings.preservation = 40; root.af_pair_settings.adjustment = 3
        with TemporaryDirectory() as directory:
            path = str(Path(directory)/'configuration.blend'); bpy.ops.wm.save_as_mainfile(filepath=path); bpy.ops.wm.open_mainfile(filepath=path)
            current = configuration.read(bpy.data.objects[name])
            self.assertAlmostEqual(current['blend_distance'], .7); self.assertEqual(current['preservation_weight'], 40)
            self.assertEqual(current['smoothing_max_adjustment'], 3); self.assertEqual(current['displacement'], .13)

    def test_authoring_preview_new_settings_is_non_mutating(self):
        root, _, _ = fixture(); refresh(root); original = configuration.inspect(root)
        with TemporaryDirectory() as journal:
            report = call(root, journal, 'stacking_preview', configuration=dict(blend_distance=.35, preservation_weight=50, smoothing_max_adjustment=2))
            self.assertEqual(report['status'], 'success', report)
            self.assertEqual(configuration.inspect(root), original)
            self.assertIn('vector-localized-v1', str(report))

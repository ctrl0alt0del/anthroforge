import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'tests'), str(Path(__file__).parent)]
from _helpers import BlenderTestCase, root
from adapters.topology.vendor import ensure_worker_dependencies
ensure_worker_dependencies()
import bpy
import numpy as np
from unittest.mock import patch
from test_topology_integration import draft_skin, loop_proxy
from adapters.topology.capture import capture_topology
from adapters.topology.solver import _transitions


class QuadWildIntegrationTests(BlenderTestCase):
    def test_branched_patches_supply_soft_flow_without_hard_seams(self):
        from types import SimpleNamespace
        from adapters.topology.flow_capture import append_patches
        grid=np.array([[[x,y,0.] for x in range(5)] for y in range(5)])
        patches=(('main',grid,False,None),('branch',grid+[0,4,0],False,{'parent':'main'}))
        samples,paths,regions=[],[],[]
        append_patches(SimpleNamespace(id='m',name='Muscle'),'MIRROR',patches,True,samples,paths,regions)
        self.assertEqual(paths,[]); self.assertEqual(len(samples),2)
        self.assertEqual(regions[1]['seam'],{'parent':'main'})
        self.assertEqual(regions[1]['role'],'MIRROR')
        self.assertEqual(set(samples[1][:,9]),{1.})

    def test_explicit_flow_is_captured_separately_from_loops(self):
        obj = root(); fiber = obj.af_vcp_system.fibers.add(); fiber.id = 'flow'; fiber.topology_flow_guide = True
        draft_skin(obj); loop_proxy(obj, fiber.id, 'Flow')
        bpy.context.view_layer.update()
        data = capture_topology(obj, bpy.context.scene, bpy.context.evaluated_depsgraph_get())
        self.assertEqual(data.settings.backend, 'QUADWILD'); self.assertEqual(len(data.guides), 0)
        self.assertEqual(len(data.flow_guides), 1); self.assertGreater(len(data.flow_samples), 0)

    def test_backend_persists_in_duplicate(self):
        obj = root(); obj.af_topology_settings.backend = 'INSTANT'
        duplicate = obj.copy(); bpy.context.scene.collection.objects.link(duplicate)
        self.assertEqual(duplicate.af_topology_settings.backend, 'INSTANT')
        obj.af_topology_settings.backend = 'QUADWILD'
        self.assertEqual(duplicate.af_topology_settings.backend, 'INSTANT')

    def test_failed_guide_join_is_explicit_quality_notice(self):
        points = np.eye(3); faces = np.array([[0, 1, 2, 0]])
        with patch('adapters.topology.solver.instant.guide_transitions', side_effect=RuntimeError('odd boundary')):
            transitions, notices = _transitions(points, faces, (), None, True)
            self.assertEqual(transitions, ()); self.assertEqual(notices[0]['mode'], 'UNSTITCHED')
            with self.assertRaisesRegex(RuntimeError, 'odd boundary'): _transitions(points, faces, (), None, False)

    def test_reference_preparation_failure_is_reported(self):
        import tempfile
        from types import SimpleNamespace
        from workers.deformation_construction import attempt
        with tempfile.TemporaryDirectory() as directory:
            spec = SimpleNamespace(cancel_path=str(Path(directory)/'cancel'))
            result = SimpleNamespace(statistics={})
            with patch('workers.deformation_construction.prepare', side_effect=RuntimeError('bounded preparation timeout')):
                attempt(spec, result, None)
            self.assertIn('timeout', result.statistics['deformation_preparation_error'])
            self.assertEqual(len(result.statistics['warnings']), 1)


if __name__ == '__main__':
    import unittest
    unittest.main(argv=[sys.argv[0]])

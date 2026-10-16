import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from core.topology.model import TopologyCapture, TopologySettings, TopologyGuide
from core.topology.protocol import write_capture, read_capture, capture_hash
from core.topology.quadwild_bundle import verify_bundle
from core.topology.quadwild_io import read_obj
from core.topology.flow_native import solve, route
from core.topology.status import TopologyCancelled
from core.topology.process import execute


class QuadWildTests(unittest.TestCase):
    def test_flow_persistence_and_signature(self):
        v = np.eye(3); f = np.array([[0, 1, 2]]); settings = TopologySettings()
        samples = np.zeros((1, 10)); path = TopologyGuide(0, 'muscle', 'muscle', 'SOURCE', v[:2])
        signature = lambda x: capture_hash('root', v, f, (), settings, None, samples=x, paths=(path,))
        capture = TopologyCapture('root', v, f, (), v.min(0), v.max(0), signature(samples), settings,
                                  flow_samples=samples, flow_guides=(path,))
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory)/'input.npz'; write_capture(file, capture); loaded = read_capture(file)
        np.testing.assert_array_equal(loaded.flow_samples, samples)
        np.testing.assert_array_equal(loaded.flow_guides[0].points, path.points)
        self.assertNotEqual(signature(samples), signature(samples+1))
        self.assertEqual(loaded.settings.backend, 'QUADWILD')

    def test_bundle_detects_corruption(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'x.exe').write_bytes(b'wrong')
            (root/'manifest.json').write_text(json.dumps(dict(files={'x.exe':'bad'})))
            with self.assertRaisesRegex(RuntimeError, 'corrupt'): verify_bundle(root)

    def test_field_and_path_native(self):
        v = np.array([[0., 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]])
        f = np.array([[0, 1, 2], [0, 2, 3]]); prior = np.array([[1., 0, 0], [1, 0, 0]])
        samples = np.array([[.5, .5, 0, 1, 0, 0, 0, 0, 1, 0.]])
        field, info = solve(v, f, prior, samples)
        self.assertTrue(np.isfinite(field).all()); self.assertEqual(field.shape, (2, 3))
        self.assertGreater(len(route(v, f, v[[0, 2]])), 0)
        with self.assertRaises(ValueError): solve(v, np.array([[0, 1, 99]]), prior, samples)

    def test_obj_invalid_identity_blocks(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'bad.obj'; path.write_text('v 0 0 0\nf 1 2 3 4\n')
            with self.assertRaisesRegex(ValueError, 'identities'): read_obj(path, 4)

    def test_cancel_stops_native_process(self):
        import sys
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(TopologyCancelled):
                execute([sys.executable, '-c', 'import time; time.sleep(30)'], folder, 'cancel', lambda: True)

    def test_memory_limit_stops_native_process(self):
        import sys
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(MemoryError):
                execute([sys.executable, '-c', 'import time; time.sleep(30)'], folder, 'memory', budget=1)

    def test_unsupported_patch_is_distinct_from_other_native_failure(self):
        from core.topology.quadwild import check_exit, UnsupportedPatchGraph
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder)/'failed.log'; log.write_text('fatal error: valence not handled: 2')
            with self.assertRaises(UnsupportedPatchGraph): check_exit({'exit_code':1}, log)
            log.write_text('unrelated failure')
            with self.assertRaises(RuntimeError) as error: check_exit({'exit_code':1}, log)
            self.assertNotIsInstance(error.exception, UnsupportedPatchGraph)

    def test_missing_new_output_never_uses_old_mesh(self):
        from core.topology.quadwild import quantize
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); config = root/'config/main_config'; config.mkdir(parents=True)
            (config/'flow.txt').write_text('scaleFact 1')
            stale = root/'mesh_rem_p0_1_quadrangulation_smooth.obj'; stale.write_text('stale')
            with patch('core.topology.quadwild.execute', return_value={'exit_code':2147483651}):
                with self.assertRaises(FileNotFoundError): quantize(root, root, 1, 0, [])
            self.assertFalse(stale.exists())


if __name__ == '__main__': unittest.main()

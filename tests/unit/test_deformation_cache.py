import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
from core.deformation import disk_cache
from core.deformation.cache import SolverCache


class DeformationCacheTests(unittest.TestCase):
    def test_corrupt_disposable_cache_is_not_loaded(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name); source = folder/'source'; source.mkdir(); cache = folder/'cache'; cache.mkdir()
            output = folder/'output'; output.mkdir(); blob = source/'bbw_v1_42.bin'; blob.write_bytes(b'weights')
            with patch.object(disk_cache,'directory',return_value=cache):
                disk_cache.retain(source); disk_cache.restore(output)
                self.assertEqual((output/blob.name).read_bytes(),b'weights')
                (output/blob.name).unlink(); (cache/blob.name).write_bytes(b'corrupt')
                disk_cache.restore(output); self.assertFalse((output/blob.name).exists())

    def test_reference_method_settings_invalidate_preparation(self):
        with patch('core.deformation.cache.PreparedSolver',side_effect=lambda *args:MagicMock()) as factory:
            cache = SolverCache(); ref = SimpleNamespace(signature='reference')
            first = cache.acquire(ref,'LE',{},'a'); self.assertIs(first,cache.acquire(ref,'LE',{},'b'))
            self.assertEqual(factory.call_count,1); first.set_cancel_path.assert_called_with('b')
            second = cache.acquire(ref,'FAST',{},'c'); first.close.assert_called_once()
            third = cache.acquire(ref,'FAST',{'fast_handles':64},'d'); second.close.assert_called_once()
            ref.signature = 'replacement'; cache.acquire(ref,'FAST',{'fast_handles':64},'e')
            third.close.assert_called_once(); self.assertEqual(factory.call_count,4); cache.clear()

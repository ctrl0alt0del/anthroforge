import unittest
from dataclasses import replace
from unittest.mock import Mock
import numpy as np
from core.vcp.prepared_cache import PreparedCache
from core.vcp.muscle_numeric import make_muscle_request
from core.vcp.muscle_profile_numeric import prepare_profile, prepared_key, PreparedBase
from core.vcp.free_muscle_numeric import _native
from test_muscle_numeric_native import _spec, _points


class PreparationCacheTests(unittest.TestCase):
    def test_public_mapping_cannot_bypass_accounting(self):
        cache = PreparedCache()
        with self.assertRaises(TypeError): cache['unaccounted'] = np.ones(8)
        self.assertEqual((len(cache), cache.bytes), (0, 0))

    def test_more_than_32_entries_are_retained_and_frozen(self):
        cache = PreparedCache()
        for index in range(100): cache.get_or_create(index, lambda: np.ones(16), 1000000)
        self.assertEqual(len(cache), 100)
        self.assertFalse(cache[0][0].flags.writeable)
        self.assertEqual(cache.bytes, sum(row[1] for row in cache.values()))

    def test_eviction_retains_active_result_and_updates_accounting(self):
        cache = PreparedCache()
        active = cache.get_or_create('a', lambda: np.ones(8), 1000)
        for key in ['b', 'c', 'd']: cache.get_or_create(key, lambda: np.zeros(8), 1000)
        self.assertNotIn('a', cache)
        self.assertTrue(np.array_equal(active, np.ones(8)))
        self.assertLessEqual(cache.bytes, 1000)
        self.assertEqual(cache.bytes, sum(row[1] for row in cache.values()))
        cache.clear(); self.assertEqual(cache.bytes, 0)

    def test_lru_hits_and_oversized_results(self):
        cache = PreparedCache(); factory = Mock(return_value=np.ones(8))
        cache.get_or_create('a', factory, 10000)
        cache.get_or_create('a', factory, 10000)
        factory.assert_called_once()
        result = cache.get_or_create('large', lambda: np.ones(10000), 10000)
        self.assertNotIn('large', cache)
        self.assertEqual(len(result), 10000)

    def test_prepared_base_survives_cache_eviction(self):
        request = make_muscle_request('M', _points(), _spec())
        prepared = PreparedBase(prepared_key(request, 'NATIVE'), object())
        execute = Mock(side_effect=AssertionError('unexpected recomputation'))
        self.assertIs(prepare_profile(replace(request, prepared_base=prepared), 'NATIVE', execute), prepared.result)

    def test_disabled_inflation_has_no_weight_preparation(self):
        spec = type('Disabled', (), {'inflation_enabled': False})()
        source = _points(); result = _native(source, spec)
        self.assertTrue(np.array_equal(source, result))
        self.assertFalse(np.shares_memory(source, result))


if __name__ == '__main__': unittest.main()

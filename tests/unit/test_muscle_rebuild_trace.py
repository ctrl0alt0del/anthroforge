from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from _muscle_rebuild_trace import NativeCall, RebuildTrace
from muscle_rebuild_report import comparable_episodes, muscle_rows


class RebuildTraceTests(unittest.TestCase):
    def setUp(self):
        self.trace = RebuildTrace()
        self.trace.active = True

    def test_disabled_trace_preserves_return_and_does_not_record(self):
        call = self.trace.wrap(lambda value: value + 1)
        self.trace.active = False
        self.assertEqual(call(3), 4)
        self.assertFalse(self.trace.rows)

    def test_nested_spans_preserve_parent_and_muscle_context(self):
        child = self.trace.wrap(lambda: 7, 'child')
        parent = self.trace.wrap(lambda muscle_id: child(), 'parent')
        self.assertEqual(parent('MUSCLE_9'), 7)
        outer, inner = self.trace.rows
        self.assertEqual((inner['parent'], inner['muscle']), (outer['id'], 'MUSCLE_9'))
        self.assertAlmostEqual(outer['self_ms'] + inner['ms'], outer['ms'])
        self.assertFalse(self.trace.stack)

    def test_exception_is_recorded_and_propagated_without_leaking_stack(self):
        call = self.trace.wrap(lambda: 1/0)
        with self.assertRaises(ZeroDivisionError): call()
        self.assertEqual(self.trace.rows[0]['exception'], 'ZeroDivisionError')
        self.assertFalse(self.trace.stack)

    def test_native_proxy_forwards_abi_configuration(self):
        original = SimpleNamespace(restype=None)
        call = NativeCall(original, lambda value: value + 1)
        call.restype = int; call.argtypes = [int]
        self.assertEqual((call(2), original.restype, call.argtypes), (3, int, [int]))

    def test_close_restores_patched_functions(self):
        original = lambda: 4
        owner = SimpleNamespace(call=original)
        self.trace.replace(owner, 'call', self.trace.wrap(original))
        self.assertEqual(owner.call(), 4)
        self.trace.close()
        self.assertIs(owner.call, original)
        self.assertFalse(self.trace.active)

    def test_geometry_result_without_error_field_is_returned_unchanged(self):
        result = SimpleNamespace(base_vertices=[(0, 0, 0)], faces=[])
        call = self.trace.wrap(lambda: result)
        self.assertIs(call(), result)
        self.assertEqual(self.trace.rows[0]['vertices'], 1)

    def test_metadata_failure_cannot_change_function_result(self):
        result = SimpleNamespace(base_vertices=None)
        self.assertIs(self.trace.wrap(lambda: result)(), result)
        self.assertIn('logging_error', self.trace.rows[0])
        self.assertFalse(self.trace.stack)

    def test_report_does_not_double_count_nested_numeric_spans(self):
        rows = [dict(id=0, parent=None, name='test.execute_muscle_work', muscle='', ms=20),
                dict(id=1, parent=0, name='numeric', muscle='MUSCLE_1', ms=10),
                dict(id=2, parent=1, name='child', muscle='MUSCLE_1', ms=7)]
        result = muscle_rows(rows, [dict(id='MUSCLE_1', name='Example')])
        self.assertEqual((result[0]['numeric'], result[0]['total']), (10, 10))

    def test_report_does_not_compare_different_inputs(self):
        episode = dict(scenario='shortcut', repeat=0, after=[])
        data = dict(sha256='fixture-a', code={'head': 'head'}, initial_meshes=[], episodes=[episode])
        other = dict(data, sha256='fixture-b')
        self.assertEqual(comparable_episodes(data, other), [])
        self.assertEqual(comparable_episodes(data, data), [True])

    def test_report_stops_comparison_after_different_action_history(self):
        shortcut = dict(scenario='shortcut', repeat=0, after=[])
        full = dict(scenario='full', repeat=0, after=[])
        data = dict(sha256='fixture', code={'head': 'head'}, initial_meshes=[], episodes=[shortcut, full])
        other = dict(data, episodes=[shortcut, dict(shortcut, repeat=1), full])
        self.assertEqual(comparable_episodes(data, other), [True])


if __name__ == '__main__': unittest.main()

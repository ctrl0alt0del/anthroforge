from types import SimpleNamespace
from unittest.mock import patch
import unittest
from core.muscle_pairs.coordinator import DetectionCoordinator
from core.muscle_pairs.model import DetectionSettings


class Backend:
    def __init__(self): self.state, self.closed, self.generation = 0, False, 0
    def submit(self, domains, settings, generation): self.generation = generation; self.state = 1
    def poll(self): return SimpleNamespace(state=self.state, message=b'failure')
    def cancel(self): self.state = 3
    def close(self): self.closed = True
    def release(self): pass
    def summary(self): return dict(pairs=({'index': 0},), timings={})
    def footprint(self, index, generation): return generation


class Capture:
    def __init__(self): self.calls, self.issues = [], ()
    def capture(self, scope, settings): self.calls.append(scope); return (), self.issues, {}


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.time = 0; self.capture = Capture()
        self.service = DetectionCoordinator(self.capture, Backend, lambda: self.time)
        self.addCleanup(self.service.reset)

    def queue(self, name='a', auto=True):
        return self.service.invalidate(name, name, DetectionSettings(), auto)

    def start(self): self.time += .2; self.service.tick()

    def complete(self):
        self.service.active[2].state = 2; self.service.tick()

    def test_debounce_coalesces(self):
        for _ in range(20): self.queue(); self.service.tick()
        self.assertEqual(self.capture.calls, []); self.start()
        self.assertEqual(self.capture.calls, ['a']); self.complete()
        self.assertEqual(self.service.inspect('a').generation, 20)

    def test_new_edit_rejects_completed_old_job(self):
        self.queue(); self.start(); old = self.service.active[2]; old.state = 2
        generation = self.queue(); self.service.tick()
        self.assertEqual(self.service.inspect('a').status, 'queued')
        self.start(); self.complete(); self.assertEqual(self.service.inspect('a').generation, generation)

    def test_roots_serialize(self):
        self.queue('a'); self.queue('b'); self.start()
        self.assertEqual(self.capture.calls, ['a']); self.complete()
        self.assertEqual(self.capture.calls, ['a', 'b']); self.complete()

    def test_invalid_inputs_remain_incomplete(self):
        self.capture.issues = ({'message': 'stale muscle'},)
        self.queue(); self.start(); self.complete()
        self.assertEqual(self.service.inspect('a').status, 'incomplete')

    def test_epoch_and_shutdown_release_everything(self):
        self.queue(); self.start(); backend = self.service.active[2]; self.service.reset()
        self.assertTrue(backend.closed); self.assertEqual(self.service.epoch, 2)
        self.assertFalse(self.service.entries)

    def test_disabled_auto_invalidates_footprint(self):
        self.queue(); self.start(); self.complete(); self.queue(auto=False)
        self.assertFalse(self.service.tick())
        with self.assertRaises(ValueError): self.service.footprint('a', 0, (1, 1))

    def test_backend_missing_explicit_unavailable(self):
        def missing(): raise RuntimeError('PAIR_NATIVE_UNAVAILABLE')
        self.service.factory = missing; self.queue(); self.start()
        self.assertEqual(self.service.inspect('a').status, 'unavailable')

    def test_removed_running_root_is_not_published(self):
        self.queue(); self.start(); self.service.remove('a')
        self.assertIsNone(self.service.active); self.assertEqual(self.service.inspect('a').status, 'not_scanned')

    def test_failed_summary_does_not_stop_other_roots(self):
        self.queue('a'); self.queue('b'); self.start()
        backend = self.service.active[2]
        with patch.object(backend, 'summary', side_effect=RuntimeError('STACK_STALE_RESULT')):
            self.complete()
        self.assertEqual(self.service.inspect('a').status, 'failed')
        self.assertIn('STACK_STALE_RESULT', self.service.inspect('a').issues[0]['message'])
        self.assertEqual(self.capture.calls, ['a', 'b']); self.complete()
        self.assertEqual(self.service.inspect('b').status, 'complete')

    def test_failed_poll_releases_backend_and_allows_retry(self):
        self.queue(); self.start(); backend = self.service.active[2]
        with patch.object(backend, 'poll', side_effect=RuntimeError('PAIR_POLL_FAILED')):
            self.service.tick()
        self.assertTrue(backend.closed)
        self.assertEqual(self.service.inspect('a').status, 'failed')
        self.queue(); self.start(); self.complete()
        self.assertEqual(self.service.inspect('a').status, 'complete')

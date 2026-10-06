import unittest
from core.warnings.repository import WarningRepository
from core.warnings.coordinator import Coordinator, WakeAfter


class SchedulingTests(unittest.TestCase):
    def test_reentrant_replacement_keeps_new_debounce_and_closes_old_job(self):
        closed, seen = [], []
        def old(token):
            try:
                self.scheduler.enqueue('root', lambda token: (seen.append('new') for _ in range(1)), delay=.150)
                yield WakeAfter(.016)
            finally: closed.append(True)
        self.scheduler.enqueue('root', old); self.scheduler.tick(max_steps=1)
        self.assertEqual(closed, [True]); self.assertEqual(self.scheduler.ready_at['root'], .150)
        self.now=.151; self.scheduler.tick(); self.assertEqual(seen, ['new'])

    def test_old_failure_cannot_remove_reentrant_replacement(self):
        seen = []
        def old(token):
            self.scheduler.enqueue('root', lambda token: (seen.append('new') for _ in range(1)))
            raise ValueError('old failure')
            yield
        self.scheduler.enqueue('root', old); self.scheduler.tick(max_steps=1)
        self.assertIn('root', self.scheduler.jobs)
        self.scheduler.tick(); self.assertEqual(seen, ['new'])
        self.assertEqual(self.scheduler.metrics['failures'], 0)

    def setUp(self):
        self.now = 0.
        self.repo = WarningRepository()
        self.scheduler = Coordinator(self.repo, clock=lambda: self.now)

    def test_latest_edit_restarts_150ms_debounce(self):
        seen = []
        builder = lambda token: (seen.append(token) for _ in range(1))
        first = self.scheduler.enqueue('root', builder, delay=.150)
        self.now = .149; self.scheduler.tick(); self.assertFalse(seen)
        latest = self.scheduler.enqueue('root', builder, delay=.150)
        self.now = .298; self.scheduler.tick(); self.assertFalse(seen)
        self.now = .2991; self.scheduler.tick(); self.assertEqual(seen, [latest])
        self.assertFalse(self.scheduler.current('root', first))

    def test_waiting_worker_does_not_block_other_root(self):
        seen = []
        self.scheduler.enqueue('a', lambda token: iter([WakeAfter(.016), 'done']))
        self.scheduler.enqueue('b', lambda token: (seen.append('b') for _ in range(1)))
        self.scheduler.tick(); self.assertEqual(seen, ['b'])
        self.assertEqual(list(self.scheduler.jobs), ['a'])
        self.now = .017; self.assertFalse(self.scheduler.tick())

    def test_tick_batches_notifications_and_nested_failure_flushes(self):
        notifications = []; self.repo.subscribe(lambda repo: notifications.append(repo.revision))
        builder = lambda token: (self.repo.state(('e', '', '', 'ROOT', str(i), 0), 'CHECKING') for i in range(5))
        self.scheduler.enqueue('root', builder); self.scheduler.tick()
        self.assertEqual(notifications, [5])
        with self.assertRaises(ValueError), self.repo.batch():
            with self.repo.batch(): self.repo.changed()
            raise ValueError('test')
        self.assertEqual(notifications, [5, 6])

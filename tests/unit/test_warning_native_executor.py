"""Warning worker ABI, ownership, parity and cancellation without Blender."""
import time
import unittest
from types import SimpleNamespace
import numpy as np
from core.warnings.native_executor import NativeWarningExecutor
from core.vcp.v2.collision import build_native_collision_world_batch
from core.vcp.v2.contracts import V2ArrayColliderSnapshot


def collider(owner='BODY', offset=0.):
    points = np.asarray(((-2., -2., offset), (2., -2., offset), (0., 2., offset)))
    matrix = np.eye(4); matrix[2, 3] = offset
    return V2ArrayColliderSnapshot(owner, owner, points, ((0, 1, 2),), transform=matrix)


def finish(worker, token):
    deadline = time.perf_counter() + 5
    while time.perf_counter() < deadline:
        status = worker.poll(token)
        if status.state >= 2: return status
        time.sleep(.001)
    raise AssertionError('Native warning job did not terminate')


def reference(colliders, pins):
    world = build_native_collision_world_batch(colliders)
    pairs, stats = [], []
    from dataclasses import replace
    for i, (point, owner, threshold) in enumerate(pins):
        batch = world.contact_pairs([point], [(0, 0)], [('', '')], 0., threshold, skip=[owner])
        pairs.extend(replace(p, edge=i) for p in batch.pairs)
        stats.append((batch.candidate_pairs, batch.tested_pairs))
    return tuple(pairs), stats


class WarningNativeTests(unittest.TestCase):
    def setUp(self):
        self.worker = NativeWarningExecutor()
        self.addCleanup(self.worker.close)

    def test_exact_contacts_and_statistics_with_transformed_capture(self):
        colliders = (collider('A', 3.), collider('B', 3.1))
        pins = (((0., 0., 3.02), 'A', .2), ((0., 0., 3.02), '', .01), ((0., 0., 3.1), 'B', .3))
        expected, counts = reference(colliders, pins)
        token = self.worker.submit(colliders, pins); self.assertEqual(finish(self.worker, token).state, 2)
        pairs, stats, elapsed = self.worker.read(token, colliders)
        self.assertEqual(pairs, expected)
        self.assertEqual([(s.candidates, s.tested) for s in stats], counts)
        self.assertGreaterEqual(elapsed, 0.)
        self.worker.release(token); self.assertFalse(self.worker.reap())

    def test_submit_copies_buffers_before_returning(self):
        source = collider(); points = source.vertices.copy()
        owned = SimpleNamespace(vertices=points, triangles=source.triangles, owner_id='BODY', collider_id='BODY')
        pins = (((0., 0., .01), '', .1),)
        expected, _counts = reference((source,), pins)
        token = self.worker.submit((owned,), pins); points[:] = 999
        finish(self.worker, token)
        self.assertEqual(self.worker.read(token, (owned,))[0], expected)
        self.worker.release(token)

    def test_cancel_reap_and_reuse(self):
        token = self.worker.submit((collider(),), (((0., 0., .01), '', .1),) * 100000)
        started = time.perf_counter(); self.worker.cancel(token)
        self.assertLess(time.perf_counter()-started, .1)
        self.assertIn(finish(self.worker, token).state, (2, 3))
        self.assertFalse(self.worker.reap())
        next_token = self.worker.submit((), ()); self.assertNotEqual(token, next_token)
        self.assertEqual(finish(self.worker, next_token).state, 2)
        self.assertEqual(self.worker.read(next_token, ())[0], ())

    def test_rejects_busy_and_invalid_snapshot(self):
        token = self.worker.submit((), ())
        with self.assertRaises(RuntimeError): self.worker.submit((), ())
        finish(self.worker, token); self.worker.release(token)
        with self.assertRaises(RuntimeError): self.worker.submit((), (((float('nan'), 0., 0.), '', .1),))
        self.assertIsNone(self.worker.job)

    def test_worker_failure_is_explicit_and_releasable(self):
        bad = SimpleNamespace(vertices=np.zeros((3, 3)), triangles=np.array([[0, 1, 99]]), owner_id='A')
        token = self.worker.submit((bad,), ())
        self.assertEqual(finish(self.worker, token).state, 4)
        with self.assertRaises(RuntimeError): self.worker.read(token, (bad,))
        self.worker.release(token)

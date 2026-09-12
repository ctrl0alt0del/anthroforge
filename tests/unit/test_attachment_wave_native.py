import unittest
from dataclasses import replace

import numpy as np

from core.vcp.attachment_wave import (AttachmentExecutorKind, AttachmentPropagationRequest,
    AttachmentSurfaceSnapshot, FiberNodeAttachmentOperation, SCPAttachmentOperation)
from core.vcp.attachment_wave_native import attachment_wave_status, execute_attachment_wave


def _surface(owner):
    vertices = np.asarray(((0, 0, 0), (1, 0, 0), (0, 1, 0)), dtype=np.float64)
    triangles = np.asarray(((0, 1, 2),), dtype=np.int64)
    return AttachmentSurfaceSnapshot(str(owner), owner, vertices, triangles,
        np.eye(4), np.eye(3), (owner,))


def _scp(child, parent, surface, depth, offset):
    return SCPAttachmentOperation(str(child), str(parent), child, parent, surface, depth,
        (0, 1, 2), (.25, .25, .5), (0, 1, 2), (.25, .25, .5), 0, True,
        (1, 0, 0), offset, (0, 0, 0), (1, 0, 0), (0, 0, 1), (1, 1, 1))


def _request(node_count=300):
    nodes = tuple(FiberNodeAttachmentOperation("F", index, 2, 2, (0, 1, 2),
        (.25, .25, .5), (0, 0, .01 * index)) for index in range(node_count))
    matrices = np.repeat(np.eye(4)[None], 3, axis=0).reshape((3, 16))
    rotations = np.repeat(np.eye(3)[None], 3, axis=0).reshape((3, 9))
    return AttachmentPropagationRequest(1, 1, 1, ("0", "1", "2"), matrices, rotations,
        (0, 0, 0), (_surface(0), _surface(1), _surface(2)),
        (_scp(1, 0, 0, 0, (0, 0, 1)), _scp(2, 1, 1, 1, (0, 0, 2))),
        ((0,), (1,)), ("F",), (node_count,), nodes, ())


class AttachmentWaveNativeTests(unittest.TestCase):
    def test_blended_contributions_have_independent_outputs(self):
        request = _request(300); first, *remaining = request.fiber_operations
        extra = replace(first, owner_index=0, surface_index=0, influence_weight=.75)
        request = replace(request, fiber_operations=(replace(first, influence_weight=.25), extra, *remaining))
        serial = execute_attachment_wave(request, AttachmentExecutorKind.SERIAL_REFERENCE)
        parallel = execute_attachment_wave(request)
        np.testing.assert_array_equal(serial.fiber_points, parallel.fiber_points)
        self.assertAlmostEqual(serial.fiber_points[0][0, 2], .75)
        self.assertAlmostEqual(serial.fiber_points[0][1, 2], 3.01)
        self.assertEqual(serial.fiber_status, (0,))

    def test_secondary_failure_does_not_poison_another_fiber(self):
        request = _request(2); first, second = request.fiber_operations
        good = replace(first, fiber_id='OTHER')
        bad = replace(first, surface_index=-1, influence_weight=.5)
        request = replace(request, fiber_ids=('F', 'OTHER'), fiber_counts=(2, 1),
                          fiber_operations=(good, replace(first, influence_weight=.5), second, bad))
        result = execute_attachment_wave(request)
        self.assertEqual(result.fiber_status, (1, 0))
        self.assertEqual(len(result.fiber_points[1]), 1)
        self.assertAlmostEqual(result.fiber_points[1][0, 2], 3)

    def test_failed_secondary_contribution_fails_only_its_fiber(self):
        request = _request(2); first, second = request.fiber_operations
        extra = replace(first, surface_index=-1, influence_weight=.5)
        request = replace(request, fiber_operations=(replace(first, influence_weight=.5), extra, second))
        self.assertEqual(execute_attachment_wave(request).fiber_status, (1,))

    def test_missing_or_invalid_weight_cannot_enter_native_kernel(self):
        request = _request(2)
        for operations in ((request.fiber_operations[0],), (replace(request.fiber_operations[0], influence_weight=.5),)):
            with self.assertRaises(ValueError): execute_attachment_wave(replace(request, fiber_operations=operations))

    def test_parallel_matches_serial_with_stable_indexed_output(self):
        request = _request(); self.assertTrue(attachment_wave_status())
        serial = execute_attachment_wave(request, AttachmentExecutorKind.SERIAL_REFERENCE)
        parallel = execute_attachment_wave(request, AttachmentExecutorKind.NATIVE_WAVE)
        np.testing.assert_array_equal(parallel.matrices, serial.matrices)
        np.testing.assert_array_equal(parallel.fiber_points[0], serial.fiber_points[0])
        self.assertEqual(parallel.fiber_status, (0,)); self.assertEqual(serial.fiber_status, (0,))

    def test_descendant_reads_parent_result_after_wave_barrier(self):
        result = execute_attachment_wave(_request(1), AttachmentExecutorKind.SERIAL_REFERENCE)
        self.assertAlmostEqual(result.matrices[1, 11], 1.0)
        self.assertAlmostEqual(result.matrices[2, 11], 3.0)
        self.assertAlmostEqual(result.fiber_points[0][0, 2], 3.0)

    def test_parallel_activation_uses_declared_cost_threshold(self):
        small = dict(execute_attachment_wave(_request(1)).telemetry)
        large = dict(execute_attachment_wave(_request(300)).telemetry)
        self.assertEqual((small["cost"], small["parallel"]), (33, 0))
        self.assertEqual((large["cost"], large["parallel"]), (332, int(large["workers"] > 1)))


if __name__ == "__main__":
    unittest.main()

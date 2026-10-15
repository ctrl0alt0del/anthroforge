import tempfile
import unittest
from pathlib import Path
import numpy as np
from core.deformation.contact import configured_library
from core.deformation.native import array


def contact(start, target, faces, cancel="", budget=2**26, reference=None):
    lib = configured_library(); output = np.empty_like(start); stats = np.zeros(8)
    ids = np.full(len(start),-1,np.int32)
    ok = lib.af_ad_contact(array(start if reference is None else reference),array(start),array(target),len(start),array(faces,True),
        len(faces),ids,np.zeros(6),budget,cancel.encode(),output,stats)
    if not ok: raise RuntimeError(lib.af_ad_error().decode())
    return output, stats


def sheets():
    points = np.array([[0,0,0],[2,0,0],[0,2,0],[.2,.2,1],[.6,.2,1],[.2,.6,1]],float)
    return points, np.array([[0,1,2],[3,4,5]],np.int32)


class NativeContactTests(unittest.TestCase):
    def test_correction_does_not_depend_on_previous_displayed_pose(self):
        reference, faces = sheets(); target = reference.copy(); target[3:,2] = -1
        prior = reference.copy(); prior[3:,0] += .3
        first, _ = contact(reference,target,faces,reference=reference)
        second, _ = contact(prior,target,faces,reference=reference)
        np.testing.assert_array_equal(first,second)

    def test_reference_preserves_side_after_touching(self):
        reference, faces = sheets(); start = reference.copy(); start[3:,2] = 0
        target = start.copy(); target[3:,2] = -1
        output, stats = contact(start,target,faces,reference=reference)
        self.assertGreater(np.linalg.norm(output-target),.1)
        self.assertLess(stats[4],1e-7)

    def test_touching_is_allowed_and_can_reopen(self):
        start, faces = sheets(); target = start.copy(); target[3:,2] = 0
        output, stats = contact(start,target,faces)
        np.testing.assert_allclose(output,target,atol=1e-10)
        output, stats = contact(target,start,faces)
        np.testing.assert_allclose(output,start,atol=1e-10)

    def test_crossing_motion_is_corrected(self):
        start, faces = sheets(); target = start.copy(); target[3:,2] = -1
        output, stats = contact(start,target,faces)
        self.assertGreater(np.linalg.norm(output-target),.1)
        self.assertLess(stats[4],1e-7)

    def test_adjacent_elements_are_excluded(self):
        start, faces = sheets(); faces[1] = [0,1,3]
        target = start.copy(); target[3:,2] = -1
        output, stats = contact(start,target,faces)
        np.testing.assert_allclose(output,target)

    def test_cancellation_and_budget(self):
        start, faces = sheets()
        with self.assertRaisesRegex(RuntimeError,"MEMORY_LIMIT"): contact(start,start,faces,budget=1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"cancel"; path.touch()
            with self.assertRaisesRegex(RuntimeError,"CANCELLED"): contact(start,start,faces,str(path))

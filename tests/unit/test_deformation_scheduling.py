import unittest
from core.deformation.scheduling import Revision, UpdateQueue


def revision(value):
    return Revision("epoch", "reference", "LE", str(value))


class DeformationSchedulingTests(unittest.TestCase):
    def test_burst_coalesces_and_late_results_never_publish(self):
        queue = UpdateQueue(); cancelled = []
        queue.enqueue("root",revision(0),0); assert not queue.ready(.2)
        queue.enqueue("root",revision(1),.2); assert not queue.ready(.4)
        first = queue.start("root",lambda:cancelled.append(True),.6)
        queue.enqueue("root",revision(2),.7); queue.enqueue("root",revision(3),.8)
        assert cancelled == [True] and not queue.ready(2)
        assert not queue.finish("root",first,revision(3))
        assert queue.ready(2) == ("root",)
        latest = queue.start("root",lambda:None,2)
        assert latest == revision(3) and queue.finish("root",latest,latest)


    def test_roots_independent_and_reset_invalidates_inflight(self):
        queue = UpdateQueue(); cancelled = []
        for root in ("a","b"): queue.enqueue(root,revision(0),0)
        stamp = queue.start("a",lambda:cancelled.append("a"),1)
        assert queue.ready(1) == ("b",)
        queue.reset()
        assert cancelled == ["a"] and not queue.finish("a",stamp,stamp)


    def test_cancel_keeps_worker_slot_until_exit(self):
        queue = UpdateQueue(); queue.enqueue("root",revision(0),0)
        stamp = queue.start("root",lambda:None,1); queue.cancel("root")
        queue.enqueue("root",revision(1),2)
        assert not queue.ready(3)
        assert not queue.finish("root",stamp,stamp)
        assert queue.ready(3) == ("root",)

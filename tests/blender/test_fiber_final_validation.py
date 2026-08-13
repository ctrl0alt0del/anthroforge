from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mathutils import Vector

ADDON_ROOT = Path(__file__).resolve().parents[2]
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from anthroforge.core.vcp import fiber_validation
from anthroforge.core.vcp.fiber_progressive import (
    FiberLevelState, FiberSolveSession, _finish_session)
from anthroforge.core.vcp.fiber_solver import FiberSolver
from anthroforge.core.vcp.fiber_validation import advance_validation, begin_final_validation


def _points(z=0.0):
    return [Vector((0.0, 0.0, 0.0)), Vector((1.0, 0.0, z)), Vector((2.0, 0.0, 0.0))]


def _residual_steps(value):
    if False:
        yield None
    return float(value)


def _run_progressive_validation(session, residual_fn):
    work = begin_final_validation(session)
    factory = lambda _solver, nodes, *_args: _residual_steps(residual_fn(nodes))
    with patch.object(fiber_validation, "_final_residual_steps", side_effect=factory), \
         patch.object(session.solver, "_active_colliders", return_value=[]):
        return advance_validation(work, float("inf"))


def _session(converged=False, loop=False):
    solver, fiber, nodes = FiberSolver(), SimpleNamespace(id="F"), _points()
    session = FiberSolveSession(solver, None, fiber, None, None)
    params = {"eps_pen": 0.1, "margin": 0.0, "segment_collisions": True}
    session.level = FiberLevelState(nodes, set(), {}, params,
                                    _points(), [], None, None, converged=converged)
    session.counts, session.route_seed, session.loop = [3], _points(), loop
    return session


class FiberFinalValidationTests(unittest.TestCase):
    def test_sync_preserves_safe_refined_candidate(self):
        solver, nodes, seed = FiberSolver(), _points(0.5), _points()
        params = {"eps_pen": 0.1}
        with patch.object(solver, "_final_residual", return_value=0.0):
            converged, disp, pen = solver._restore_and_validate_open(
                nodes, seed, object(), params, {}, True, 0.01, 0.0)
        self.assertEqual((nodes[1].z, converged, disp, pen), (0.5, True, 0.01, 0.0))

    def test_sync_uses_clear_seed_only_for_unsafe_candidate(self):
        solver, nodes, seed = FiberSolver(), _points(0.5), _points()
        params = {"eps_pen": 0.1}
        with patch.object(solver, "_final_residual", side_effect=lambda pts, *_: abs(pts[1].z)):
            converged, disp, pen = solver._restore_and_validate_open(
                nodes, seed, object(), params, {}, True, 0.01, 0.5)
        self.assertEqual((nodes[1].z, converged, disp, pen), (0.0, False, 0.5, 0.0))

    def test_progressive_preserves_safe_refined_candidate(self):
        session = _session(converged=True)
        session.level.nodes, session.route_seed = _points(0.5), _points()
        self.assertTrue(_run_progressive_validation(session, lambda _nodes: 0.0))
        self.assertEqual((session.level.nodes[1].z, session.level.converged), (0.5, True))

    def test_progressive_seed_fallback_is_revalidated_and_nonconverged(self):
        session = _session(converged=True)
        session.level.nodes, session.route_seed = _points(0.5), _points()
        self.assertTrue(_run_progressive_validation(session, lambda pts: abs(pts[1].z)))
        values = session.level.nodes[1].z, session.level.converged
        self.assertEqual((*values, session.level.max_disp, session.level.max_pen), (0.0, False, 0.5, 0.0))

    def test_nonconverged_loop_preserves_last_good_caches(self):
        session = _session(converged=False, loop=True)
        solver, key, old = session.solver, session.solver._fiber_cache_key(session.fiber), _points(0.5)
        solver._cache[key], solver._loop_cache_signatures[key] = old, "last-good"
        with patch.object(solver, "_store_status"), patch.object(solver, "_store_metrics"), \
             patch.object(solver, "_store_loop_cache_signature") as signature:
            _finish_session(session, False, True)
        self.assertIs(solver._cache[key], old)
        self.assertEqual((solver._loop_cache_signatures[key], signature.call_count), ("last-good", 0))


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mathutils import Vector

ADDON_ROOT = Path(__file__).resolve().parents[2]
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from anthroforge.core.vcp.fiber_engine import FiberPhase
from anthroforge.core.vcp.fiber_progressive import (
    FiberLevelState, FiberSolveSession, _advance_session,
)
from anthroforge.core.vcp.fiber_solver import FiberSolver


def _points():
    return [Vector((0.0, 0.0, 0.0)), Vector((1.0, 1.0, 0.0)),
            Vector((2.0, 0.0, 0.0))]


def _session():
    solver = FiberSolver()
    params = {"margin": 0.0, "shorten_strength": 0.5, "bend_strength": 0.0,
              "segment_collisions": False, "solver_version": 1, "eps_pen": 1e-5,
              "iterations": 1, "min_iters": 1, "eps_disp": 1e-5}
    nodes = _points()
    session = FiberSolveSession(solver, None, SimpleNamespace(id="F"), None, None)
    session.oracle = SimpleNamespace(push_out_point=lambda point, _cols: (point.copy(), 0.0))
    session.level = FiberLevelState(nodes, [True, False, True],
                                    {0: nodes[0], 2: nodes[2]}, params,
                                    _points(), (), _points(), _points())
    session.phase = FiberPhase.LOCAL_STEP.value
    return session


class FiberMicrobatchTests(unittest.TestCase):
    def test_iteration_crosses_named_resumable_phases(self):
        session = _session()
        with patch.object(session.solver, "_active_colliders", return_value=()), \
             patch.object(session.solver, "_post_iteration_state",
                          return_value=(_points(), (), _points())):
            phases = _advance_phases(session, 5)
        self.assertEqual(phases[:5], ["GLOBAL_STEP", "CONTACTS", "LINE_SEARCH",
                                     "ACCEPT", "FINAL_VALIDATE"])


def _advance_phases(session, count):
    phases = []
    for _index in range(count):
        _advance_session(session, 0.0)
        phases.append(session.phase)
    return phases


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from _support import ensure_import_path, install_fake_modules

ensure_import_path()
install_fake_modules()

from core.vcp import fiber_anchor_preflight as preflight
from core.vcp.v2.contracts import V2AnchorRole


class Pointer:
    def __init__(self, value):
        self.value = value

    def as_pointer(self):
        return self.value


class World:
    def __init__(self, pairs):
        self.pairs = tuple(pairs)
        self.calls = []

    def contact_pairs(self, points, edges, owners, span, threshold, skip=()):
        self.calls.append((points.copy(), edges.copy(), owners, span, threshold, skip))
        return SimpleNamespace(pairs=self.pairs, candidate_pairs=9, tested_pairs=7)


def anchor(role=V2AnchorRole.TOUCH, index=1, owner="SCP_10", point=(1.0, 2.0, 3.0)):
    return preflight.FiberHardAnchor(point, owner, role, index)


def collider(cid, owner):
    return SimpleNamespace(collider_id=cid, owner_id=owner)


def pair(edge, cid, distance, contained=False):
    return SimpleNamespace(edge=edge, collider_id=cid, distance=distance, contained=contained)


def loop_fiber():
    specs = tuple(SimpleNamespace(parent_id=f"S{index}", attach_param=str(index)) for index in range(3))
    return SimpleNamespace(id="F1", topology_mode="LOOP", loop_anchors=specs,
                           symmetry_mode="MIRROR_SEAM_LOOP", symmetry_axis="X",
                           symmetry_origin=(0.0, 0.0, 0.0), collision_radius=.002)


def stable_probe(root, scene, fiber):
    status = SimpleNamespace(version="test")
    with patch.object(preflight, "_collider_probe_rows", return_value=()), \
         patch.object(preflight, "_hierarchy_rows", return_value=()), \
         patch.object(preflight, "collision_backend_status", return_value=status):
        return preflight._probe_key(root, scene, fiber)


class FiberAnchorPreflightTests(unittest.TestCase):
    def setUp(self):
        preflight._CACHE.clear()
        from core.warnings.session import reset
        reset()

    def test_exact_owner_skip_keeps_ancestor_and_unrelated_active(self):
        rows = (anchor(),)
        cols = (collider("OWN", "SCP_10"), collider("ANC", "SCP_4"), collider("OTHER", "SCP_20"))
        world = World((pair(0, "ANC", 0.0007), pair(0, "OTHER", 0.0008)))
        result = preflight.evaluate_anchor_preflight(rows, cols, {"SCP_10": "SCP_4"}, .002, .00002, world=world)
        self.assertEqual(world.calls[0][-1], ("SCP_10",))
        self.assertEqual([(row.blocker_id, row.relation) for row in result.violations],
                         [("SCP_20", "UNRELATED"), ("SCP_4", "ANCESTOR")])

    def test_dedup_prefers_containment_then_minimum_distance(self):
        cols = (collider("A", "BLOCK"), collider("B", "BLOCK"))
        pairs = (pair(0, "A", .0001), pair(0, "B", .0015, True), pair(0, "B", .0010, True))
        result = preflight.evaluate_anchor_preflight((anchor(),), cols, {}, .002, 0.0, world=World(pairs))
        self.assertEqual(len(result.violations), 1)
        self.assertTrue(result.violations[0].contained)
        self.assertEqual(result.violations[0].measured_clearance, .0010)

    def test_effective_threshold_is_strict_and_fields_are_exact(self):
        rows = (anchor(V2AnchorRole.ENDPOINT_A, 0), anchor(V2AnchorRole.ENDPOINT_B, 1))
        cols = (collider("BLOCK", "SCP_4"),)
        pairs = (pair(0, "BLOCK", .00198), pair(1, "BLOCK", .001979))
        result = preflight.evaluate_anchor_preflight(rows, cols, {}, .002, .00002, world=World(pairs))
        violation = result.violations[0]
        self.assertEqual((violation.role, violation.authored_index), (V2AnchorRole.ENDPOINT_B, 1))
        self.assertEqual((violation.configured_clearance, violation.effective_clearance), (.002, .00198))
        self.assertEqual(violation.action, "Move or re-author the attachment on SCP_10.")

    def test_roles_indices_sort_and_touch_action_are_deterministic(self):
        rows = (anchor(V2AnchorRole.LOOP, 2, "B"), anchor(V2AnchorRole.TOUCH, 1, "A"))
        cols = (collider("Z", "Z"), collider("A", "A_BLOCK"))
        pairs = (pair(0, "Z", 0.0), pair(1, "A", 0.0))
        result = preflight.evaluate_anchor_preflight(rows, cols, {}, .002, 0.0, world=World(pairs))
        self.assertEqual([(row.authored_index, row.blocker_id) for row in result.violations], [(1, "A_BLOCK"), (2, "Z")])
        self.assertEqual(result.violations[0].action,
                         "Increase touch offset or re-author the anchor on A.")

    def test_open_and_loop_authored_roles_cover_every_anchor(self):
        rows = tuple(SimpleNamespace(point=(index, 0, 0), owner_id=str(index)) for index in range(4))
        opened = preflight._hard_anchors(SimpleNamespace(topology_mode="OPEN"), rows)
        looped = preflight._hard_anchors(SimpleNamespace(topology_mode="LOOP"), rows)
        self.assertEqual([row.role for row in opened], [V2AnchorRole.ENDPOINT_A,
                         V2AnchorRole.TOUCH, V2AnchorRole.TOUCH, V2AnchorRole.ENDPOINT_B])
        self.assertEqual([row.authored_index for row in looped], [0, 1, 2, 3])
        self.assertTrue(all(row.role is V2AnchorRole.LOOP for row in looped))

    def test_symmetric_loop_excludes_generated_mirror_pins(self):
        fiber = loop_fiber()
        authored = tuple(SimpleNamespace(point=(index, 0, 0), owner_id=f"S{index}") for index in range(3))
        generated = (SimpleNamespace(point=(-1, 0, 0), owner_id=""),)
        solver = SimpleNamespace(_loop_anchors=lambda *_args: (None, authored + generated, ""))
        rows, issue = preflight._resolve_anchors(object(), object(), fiber, solver, object())
        self.assertEqual(issue, "")
        self.assertEqual([(row.authored_index, row.owner_id) for row in rows],
                         [(0, "S0"), (1, "S1"), (2, "S2")])

    def test_symmetry_changes_preserve_authored_only_cache_probe(self):
        fiber = loop_fiber()
        root, scene = object(), object()
        before = stable_probe(root, scene, fiber)
        fiber.symmetry_mode, fiber.symmetry_axis = "NONE", "Y"
        fiber.symmetry_origin = (4.0, 5.0, 6.0)
        self.assertEqual(stable_probe(root, scene, fiber), before)

    def test_summary_counts_one_anchor_with_multiple_blockers_once(self):
        rows = (SimpleNamespace(role=V2AnchorRole.TOUCH, authored_index=4, blocker_id="A"),
                SimpleNamespace(role=V2AnchorRole.TOUCH, authored_index=4, blocker_id="B"))
        result = SimpleNamespace(violations=rows)
        self.assertEqual(preflight.anchor_preflight_summary(result),
                         "Fiber has 1 invalid hard anchor; planning cannot start.")

    def test_cache_hit_skips_anchor_mesh_and_collision_work(self):
        probe = (("Scene", 1),)
        expected = preflight.FiberAnchorPreflightResult(True, (), ("full",), 0, 0)
        preflight._CACHE[probe] = expected
        with patch.object(preflight, "_probe_key", return_value=probe), patch.object(preflight, "_resolve_anchors") as resolve:
            with patch.object(preflight, "_publish"):
                actual = preflight.preflight_fiber_hard_anchors(object(), object(), object(), object(), object())
        self.assertIs(actual, expected)
        resolve.assert_not_called()

    def test_recreated_fiber_identity_cannot_read_deleted_diagnostics(self):
        scene, root, old, fresh = Pointer(1), Pointer(2), Pointer(3), Pointer(4)
        old.id = fresh.id = "F1"
        preflight._publish(root, scene, old, preflight.FiberAnchorPreflightResult(False, (), (), 0, 0))
        self.assertIsNone(preflight.current_fiber_anchor_preflight(scene, root, fresh))


if __name__ == "__main__":
    unittest.main()

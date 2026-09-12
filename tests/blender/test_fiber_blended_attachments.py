from dataclasses import replace
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import bpy
import numpy as np
from mathutils import Vector
from _helpers import BlenderTestCase, capture_world_attachment, fiber, mesh_object, root, scp_with_object
from core.vcp.fiber_node_attachment import capture_fiber_node_attachments, resolve_fiber_node_attachments
from core.vcp.fiber_node_attachment_codec import decode_node_attachments, encode_node_attachments
from core.vcp.prop_update_guard import suppress_vcp_prop_updates


def _surface(name, x):
    obj = mesh_object(name, (x, 0, 0))
    for vertex, point in zip(obj.data.vertices, ((0, 0, 0), (0, 1, 0), (0, 0, 1))): vertex.co = point
    return obj


def _fixture():
    r = root(); left, right = _surface('Left', 0), _surface('Right', 1)
    with suppress_vcp_prop_updates():
        a, b = scp_with_object(r, 'Left', left), scp_with_object(r, 'Right', right)
        item = fiber(r, a.id, b.id); item.node_count = 41
        item.a_attach_param = capture_world_attachment(r, a.id, Vector((0, .2, .2)))
        item.b_attach_param = capture_world_attachment(r, b.id, Vector((1, .2, .2)))
    bpy.context.view_layer.update()
    points = tuple(Vector((i / 40, .2, .2)) for i in range(41))
    assert capture_fiber_node_attachments(r, bpy.context.scene, item, points).ok
    return r, right, item, points


def _resolve(r, item):
    result = resolve_fiber_node_attachments(r, bpy.context.scene, item)
    assert result.ok, result.error
    return np.asarray(result.points)


class FiberBlendedAttachmentTests(BlenderTestCase):
    def test_authored_midpoint_offset_is_not_blended(self):
        r, right, item, points = _fixture()
        with suppress_vcp_prop_updates():
            touch = item.mid_touches.add(); touch.parent_id = item.a_parent_id
            touch.attach_param = item.a_attach_param; touch.normal_offset = .5
        self.assertTrue(capture_fiber_node_attachments(r, bpy.context.scene, item, points).ok)
        self.assertFalse(decode_node_attachments(item.node_attachments_json).nodes[20].influences)
        right.location.z = .2; bpy.context.view_layer.update()
        np.testing.assert_allclose(_resolve(r, item)[20], points[20], atol=1e-6)

    def test_legacy_upgrade_preserves_primary_bindings_and_current_shape(self):
        from core.vcp.fiber_node_attachment import upgrade_fiber_node_attachments
        r, _right, item, _points = _fixture(); payload = decode_node_attachments(item.node_attachments_json)
        legacy = replace(payload, version=1, nodes=tuple(replace(row, influences=()) for row in payload.nodes))
        with suppress_vcp_prop_updates(): item.node_attachments_json = encode_node_attachments(legacy)
        before = _resolve(r, item); self.assertTrue(upgrade_fiber_node_attachments(r, bpy.context.scene, item))
        after = decode_node_attachments(item.node_attachments_json)
        self.assertEqual(tuple(replace(row, influences=()) for row in after.nodes), legacy.nodes)
        np.testing.assert_allclose(_resolve(r, item), before, atol=1e-6)
        self.assertFalse(upgrade_fiber_node_attachments(r, bpy.context.scene, item))

    def test_save_reload_does_not_recapture_blended_reference(self):
        r, _right, item, _points = _fixture(); raw = item.node_attachments_json
        root_name, fiber_id = r.name, item.id
        with tempfile.TemporaryDirectory(prefix='af_blend_bindings_') as directory:
            path = str(Path(directory) / 'attachments.blend')
            bpy.ops.wm.save_as_mainfile(filepath=path); bpy.ops.wm.open_mainfile(filepath=path)
            r = bpy.data.objects[root_name]; item = next(row for row in r.af_vcp_system.fibers if row.id == fiber_id)
            self.assertEqual(item.node_attachments_json, raw)

    def test_reference_pose_and_hard_endpoints_are_preserved(self):
        r, right, item, points = _fixture(); raw = item.node_attachments_json
        np.testing.assert_allclose(_resolve(r, item), points, atol=1e-6)
        right.location.z = .2; bpy.context.view_layer.update(); moved = _resolve(r, item)
        np.testing.assert_allclose(moved[0], points[0], atol=1e-6)
        np.testing.assert_allclose(moved[-1], np.asarray(points[-1]) + (0, 0, .2), atol=1e-6)
        self.assertLess(np.max(np.abs(np.diff(moved[:, 2]))), .025)
        self.assertEqual(item.node_attachments_json, raw)

    def test_gradual_and_direct_moves_match_and_restore(self):
        r, right, item, points = _fixture(); right.location.z = .3; bpy.context.view_layer.update()
        direct = _resolve(r, item)
        for value in (0, .1, .2, .3):
            right.location.z = value; bpy.context.view_layer.update(); gradual = _resolve(r, item)
        np.testing.assert_array_equal(direct, gradual)
        right.location.z = 0; bpy.context.view_layer.update()
        np.testing.assert_allclose(_resolve(r, item), points, atol=1e-6)

    def test_native_parallel_serial_and_python_resolution_match(self):
        from core.scp_runtime.attachment_wave_capture import capture_attachment_wave
        from core.scp_runtime.common import scp_prop_map
        from core.vcp.attachment_wave_native import execute_attachment_wave
        from core.vcp.attachment_wave import AttachmentExecutorKind
        r, right, item, _points = _fixture(); right.location.z = .2; bpy.context.view_layer.update()
        request = capture_attachment_wave(r, bpy.context.scene, scp_prop_map(r), (), (), (item,)).request
        native = execute_attachment_wave(request); serial = execute_attachment_wave(request, AttachmentExecutorKind.SERIAL_REFERENCE)
        self.assertGreater(len(request.fiber_operations), item.node_count)
        np.testing.assert_array_equal(native.fiber_points, serial.fiber_points)
        np.testing.assert_allclose(native.fiber_points[0], _resolve(r, item), atol=1e-6)

    def test_corrupt_secondary_surface_fails_whole_resolution(self):
        r, _right, item, _points = _fixture(); payload = decode_node_attachments(item.node_attachments_json)
        nodes = list(payload.nodes); index = next(i for i, row in enumerate(nodes) if len(row.influences) == 2)
        row = nodes[index]; nodes[index] = replace(row, influences=(row.influences[0], replace(row.influences[1], attach_raw='{}')))
        with suppress_vcp_prop_updates(): item.node_attachments_json = encode_node_attachments(replace(payload, nodes=tuple(nodes)))
        self.assertFalse(resolve_fiber_node_attachments(r, bpy.context.scene, item).ok)

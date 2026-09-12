import unittest
import json
from dataclasses import replace
from types import SimpleNamespace

from core.vcp.fiber_node_attachment_codec import (FiberNodeAttachment,
                                                   FiberNodeAttachmentPayload,
                                                   decode_node_attachments,
                                                   encode_node_attachments,
                                                   node_attachment_target_ids,
                                                   remap_node_attachment_targets)
from core.vcp.fiber_node_attachment_codec import FiberNodeInfluence


def _payload():
    nodes = (FiberNodeAttachment("S1", "A", (1.0, 2.0, 3.0)),
             FiberNodeAttachment("S2", "B", (4.0, 5.0, 6.0)))
    return FiberNodeAttachmentPayload(1, 2, False, nodes)


class FiberNodeAttachmentCodecTests(unittest.TestCase):
    def test_blended_round_trip_and_complete_remapping(self):
        item = FiberNodeInfluence('S3', 'C', (0, 0, 0), .4)
        node = replace(_payload().nodes[0], influences=(replace(item, target_id='S1', weight=.6), item))
        payload = replace(_payload(), version=2, nodes=(node, _payload().nodes[1]))
        raw = encode_node_attachments(payload); self.assertEqual(decode_node_attachments(raw), payload)
        self.assertEqual(node_attachment_target_ids(SimpleNamespace(node_attachments_json=raw)), ('S1', 'S3', 'S2'))
        self.assertEqual(remap_node_attachment_targets(raw, {'S1': 'A', 'S2': 'B'}), '')
        remapped = decode_node_attachments(remap_node_attachment_targets(raw, {'S1': 'A', 'S2': 'B', 'S3': 'C'}))
        self.assertEqual(remapped.nodes[0].influences[1].target_id, 'C')

    def test_bad_blend_weights_and_nested_influences_are_rejected(self):
        value = json.loads(encode_node_attachments(replace(_payload(), version=2)))
        item = dict(value['nodes'][0], weight=.4)
        for weight in (-1, float('nan'), .4, 2):
            value['nodes'][0]['influences'] = [dict(item, weight=weight)]
            self.assertIsNone(decode_node_attachments(json.dumps(value)))
        value['nodes'][0]['influences'] = [dict(item, weight=1, influences=[])]
        self.assertIsNone(decode_node_attachments(json.dumps(value)))

    def test_round_trip(self):
        payload = _payload()
        self.assertEqual(decode_node_attachments(encode_node_attachments(payload)), payload)

    def test_invalid_payload_is_rejected(self):
        self.assertIsNone(decode_node_attachments(""))
        self.assertIsNone(decode_node_attachments('{"version":1,"point_count":2,"nodes":[]}'))

    def test_targets_are_stable_and_unique(self):
        raw = encode_node_attachments(_payload())
        fiber = SimpleNamespace(node_attachments_json=raw)
        self.assertEqual(node_attachment_target_ids(fiber), ("S1", "S2"))

    def test_remap_requires_complete_scp_scope(self):
        raw = encode_node_attachments(_payload())
        self.assertEqual(remap_node_attachment_targets(raw, {"S1": "S9"}), "")
        mapped = decode_node_attachments(remap_node_attachment_targets(raw, {"S1": "S9", "S2": "S8"}))
        self.assertEqual(tuple(row.target_id for row in mapped.nodes), ("S9", "S8"))


if __name__ == "__main__":
    unittest.main()

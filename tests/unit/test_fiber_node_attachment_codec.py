import unittest
from types import SimpleNamespace

from core.vcp.fiber_node_attachment_codec import (FiberNodeAttachment,
                                                   FiberNodeAttachmentPayload,
                                                   decode_node_attachments,
                                                   encode_node_attachments,
                                                   node_attachment_target_ids,
                                                   remap_node_attachment_targets)


def _payload():
    nodes = (FiberNodeAttachment("S1", "A", (1.0, 2.0, 3.0)),
             FiberNodeAttachment("S2", "B", (4.0, 5.0, 6.0)))
    return FiberNodeAttachmentPayload(1, 2, False, nodes)


class FiberNodeAttachmentCodecTests(unittest.TestCase):
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

"""Shared assets never share mutable journal records or require the pool to read."""
import hashlib
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from core.authoring.storage import FileStore
from core.authoring.storage_pool import policy


def enable(root):
    value = dict(schema_version=1, immutable_asset_pool='pool', compress_journals=False)
    (root / '.authoring-storage.json').write_text(json.dumps(value))


class StoragePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        enable(self.root)
        self.left = FileStore(self.root / 'left.authoring')
        self.right = FileStore(self.root / 'right.authoring')

    def test_identical_assets_share_storage_and_remain_portable(self):
        left = self.left.asset({'vertices': [1, 2, 3]})
        right = self.right.asset({'vertices': [1, 2, 3]})
        a, b = Path(left['path']), Path(right['path'])
        self.assertTrue(a.samefile(b))
        pool = self.root / 'pool' / left['sha256'][:2] / a.name
        pool.unlink()
        self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertEqual(hashlib.sha256(a.read_bytes()).hexdigest(), left['sha256'])

    def test_mutable_records_remain_independent(self):
        self.left.put('v04_drafts', 'key', {'revision': 1})
        self.right.put('v04_drafts', 'key', {'revision': 1})
        self.assertFalse(self.left.path('v04_drafts', 'key').samefile(self.right.path('v04_drafts', 'key')))
        self.left.put('v04_drafts', 'key', {'revision': 2})
        self.assertEqual(self.right.get('v04_drafts', 'key'), {'revision': 1})

    def test_corrupt_pool_is_rejected(self):
        value = self.left.asset({'x': 1})
        Path(value['path']).write_text('corrupt')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.right.asset({'x': 1})

    def test_link_failure_keeps_normal_readable_asset(self):
        with patch('core.authoring.storage_pool.os.link', side_effect=OSError('no links')):
            value = self.left.asset({'x': 1})
        self.assertEqual(json.loads(Path(value['path']).read_text()), {'x': 1})

    def test_policy_cannot_escape_its_root(self):
        (self.root / '.authoring-storage.json').write_text(json.dumps(dict(
            schema_version=1, immutable_asset_pool='../escape', compress_journals=False)))
        with self.assertRaisesRegex(ValueError, 'inside'):
            policy(self.root / 'left.authoring')

    def test_no_policy_preserves_legacy_storage(self):
        (self.root / '.authoring-storage.json').unlink()
        value = FileStore(self.root / 'legacy').asset({'x': 1})
        self.assertEqual(json.loads(Path(value['path']).read_text()), {'x': 1})

    def test_image_identity_and_bytes_are_unchanged(self):
        value = self.left.image('<svg>test</svg>')
        other = self.right.image('<svg>test</svg>')
        self.assertTrue(Path(value['path']).samefile(other['path']))
        self.assertEqual(Path(value['path']).read_text(), '<svg>test</svg>')

    @unittest.skipUnless(os.name == 'nt', 'NTFS test')
    def test_compression_preserves_bytes(self):
        from core.authoring.storage_windows import compress, compressed_size
        target = self.root / 'compression.json'
        content = b'{"repeated":1234}\n' * 10000
        target.write_bytes(content)
        compress(target)
        self.assertEqual(target.read_bytes(), content)
        self.assertLess(compressed_size(target), len(content))

"""Retention rejects incomplete containers, changed files and escaping paths."""
import io
import json
import os
import struct
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/muscle_workflow'))
from storage_support import safe, fingerprint
from storage_retention import blend_blocks, remove_backup, eligible_metadata


def container(modern=True, pointer='-', endian='v'):
    if modern:
        header, format = b'BLENDER17-01v0500', '<4siQqq'
        blocks = [struct.pack(format, code, 0, 0, 0, 0) for code in (b'GLOB', b'DNA1', b'ENDB')]
    else:
        header = ('BLENDER' + pointer + endian + '405').encode()
        format = ('<' if endian == 'v' else '>') + '4si' + ('Q' if pointer == '-' else 'I') + 'ii'
        blocks = [struct.pack(format, code, 0, 0, 0, 0) for code in (b'GLOB', b'DNA1', b'ENDB')]
    return header + b''.join(blocks)


class MaintenanceTests(unittest.TestCase):
    def test_reference_scan_includes_large_hashed_journal_records(self):
        row = dict(path='runs/example/data.authoring/v04_drafts/' + 'a' * 64 + '.json', bytes=30_000_000)
        self.assertTrue(eligible_metadata(row))

    def test_measure_counts_hard_link_data_once(self):
        from storage_inventory import measure
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'a').write_bytes(b'content')
            os.link(root / 'a', root / 'b')
            result = measure(root)
            self.assertEqual(result['files'], 2)
            self.assertEqual(result['unique_files'], 1)
            self.assertEqual(result['logical_bytes'], 14)
            self.assertEqual(result['stored_data_bytes'], 7)

    def test_old_and_large_block_formats(self):
        for modern in (True, False):
            for pointer in ('-', '_'):
                for endian in ('v', 'V'):
                    self.assertEqual(blend_blocks(io.BytesIO(container(modern, pointer, endian))), 3)

    def test_truncation_and_trailing_bytes_rejected(self):
        data = container()
        for broken in (data[:12], data[:-1], data + b'extra'):
            with self.assertRaises(ValueError):
                blend_blocks(io.BytesIO(broken))

    def test_missing_structures_and_negative_lengths_rejected(self):
        data = container()
        for broken in (data[:17] + data[-32:], data[:33] + struct.pack('<q', -1) + data[41:]):
            with self.assertRaises(ValueError):
                blend_blocks(io.BytesIO(broken))

    def test_safe_path_refuses_root_and_escape(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(safe(root, 'inside.txt'), root / 'inside.txt')
            for value in ('.', '../outside.txt'):
                with self.assertRaises(ValueError):
                    safe(root, value)

    def test_changed_primary_prevents_backup_deletion(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            primary, backup = root / 'test.blend', root / 'test.blend1'
            primary.write_bytes(container()); backup.write_bytes(container())
            entry = dict(path=backup.name, primary=primary.name,
                         backup=fingerprint(backup), newer=fingerprint(primary))
            primary.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'changed'):
                remove_backup(root, entry)
            self.assertTrue(backup.exists())

    def test_matching_validated_backup_is_removed(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            primary, backup = root / 'test.blend', root / 'test.blend1'
            primary.write_bytes(container()); backup.write_bytes(container())
            entry = dict(path=backup.name, primary=primary.name,
                         backup=fingerprint(backup), newer=fingerprint(primary))
            result = remove_backup(root, entry)
            self.assertEqual(result['status'], 'removed')
            self.assertTrue(primary.exists())
            self.assertFalse(backup.exists())

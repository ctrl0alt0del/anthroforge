import unittest
from tempfile import TemporaryDirectory
from core.authoring.codec import digest
from core.authoring.errors import AuthoringError
from core.authoring.request_identity import reserve, reservation, CATEGORIES
from core.authoring.storage import FileStore


class RequestIdentityTests(unittest.TestCase):
    def test_failed_dispatch_releases_only_its_new_reservation(self):
        request = dict(request_id='same', op='points.edit')
        with TemporaryDirectory() as folder:
            store = FileStore(folder)
            with self.assertRaisesRegex(ValueError, 'dispatch'):
                with reservation(store, request, ('root',)): raise ValueError('dispatch')
            self.assertIsNone(store.get('request_identities', ['root', 'same']))
            reserve(store, request, ('root',))
            with self.assertRaisesRegex(ValueError, 'dispatch'):
                with reservation(store, request, ('root',)): raise ValueError('dispatch')
            self.assertEqual(store.get('request_identities', ['root', 'same'])['digest'], digest(request))

    def test_reservation_is_durable_and_does_not_replace_live_receipts(self):
        request = dict(request_id='same', op='fibers.create_free')
        with TemporaryDirectory() as folder:
            reserve(FileStore(folder), request, ('root',))
            reopened = FileStore(folder); reserve(reopened, request, ('root',))
            self.assertIsNone(reopened.get('v04_requests', ['root', 'same']))
            with self.assertRaisesRegex(AuthoringError, 'Request id reused'):
                reserve(reopened, dict(request, op='points.edit'), ('root',))

    def test_all_legacy_families_and_root_aliases_share_conflict_guard(self):
        request = dict(request_id='same', op='points.edit')
        for category in CATEGORIES:
            with self.subTest(category=category), TemporaryDirectory() as folder:
                store = FileStore(folder); row = dict(digest=digest(request))
                store.put(category, ['old-root-name', 'same'], dict(receipt=row) if category == 'free_path_requests' else row)
                with self.assertRaisesRegex(AuthoringError, 'Request id reused'):
                    reserve(store, dict(request, op='fibers.create_free'), ('new-root-id', 'old-root-name'))

    def test_reservation_write_failure_happens_before_dispatch(self):
        from unittest.mock import patch
        with TemporaryDirectory() as folder, patch.object(FileStore, 'put', side_effect=OSError('reservation failed')):
            with self.assertRaisesRegex(OSError, 'reservation failed'):
                reserve(FileStore(folder), dict(request_id='id'), ('root',))

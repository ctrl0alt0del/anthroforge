"""Draft state and replay receipts share a single atomic record."""
from copy import deepcopy
from .codec import digest
from .errors import require


class DraftRepository:
    def __init__(self, store, scene_id):
        self.store, self.scene_id = store, scene_id

    def get(self, identity):
        return self.store.get('v04_drafts', [self.scene_id, identity])

    def all(self):
        from .codec import decode
        rows = []
        for path in (self.store.directory/'v04_drafts').glob('*.json'):
            record = decode(path.read_text(encoding='utf-8'), 256_000_000)
            identity = record['document']['document_id']
            if self.store.path('v04_drafts', [self.scene_id, identity]) == path:
                rows.append(record)
        return rows

    def commit(self, identity, expected, document, request, scene_revision, extra=None):
        old = self.get(identity) or {'draft_revision': 0, 'receipts': {}}
        replay = self.replay(old, request)
        if replay:
            return old, replay
        require(old['draft_revision'] == expected, 'STALE_DRAFT_REVISION')
        record = dict(document=deepcopy(document), draft_revision=expected+1, scene_revision=scene_revision,
                      state='pending', results={}, receipts=old['receipts'], **(extra or {}))
        receipt = dict(digest=digest(request), revision=expected+1, state='committed')
        record['receipts'][request['request_id']] = receipt
        self.store.put('v04_drafts', [self.scene_id, identity], record)
        return record, receipt

    def replay(self, record, request):
        receipt = record.get('receipts', {}).get(request['request_id'])
        if receipt:
            require(receipt['digest'] == digest(request), 'REQUEST_ID_REUSED')
        return receipt

    def finish(self, identity, revision, result):
        record = self.get(identity)
        require(record['draft_revision'] == revision, 'STALE_DRAFT_REVISION')
        record.update(result)
        self.store.put('v04_drafts', [self.scene_id, identity], record)
        return record

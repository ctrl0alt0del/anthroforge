"""One durable request namespace; operation handlers own live replay checks."""
from contextlib import contextmanager
from .codec import digest
from .errors import require

CATEGORIES = ('request_identities', 'v04_requests', 'requests', 'free_path_requests', 'v04_profile_receipts')


def reserve(store, request, scopes, receipts=()):
    scopes = tuple(dict.fromkeys(scopes)); fingerprint = digest(request)
    rows = list(receipts)
    for scope in scopes:
        rows.extend(store.get(category, [scope, request['request_id']]) for category in CATEGORIES)
    for row in filter(None, rows):
        value = row.get('receipt', row)
        require(value.get('digest') == fingerprint, 'REQUEST_ID_REUSED')
    key = [scopes[0], request['request_id']]
    if not store.get('request_identities', key):
        store.put('request_identities', key, dict(digest=fingerprint))
        return key


@contextmanager
def reservation(store, request, scopes, receipts=()):
    created = reserve(store, request, scopes, receipts)
    try: yield
    except BaseException:
        if created is not None: store.path('request_identities', created).unlink(missing_ok=True)
        raise

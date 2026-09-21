"""Root receipt migration into the shared durable authoring request namespace."""
from ...core.authoring.codec import decode
from ...core.authoring.request_identity import reservation


def request_scope(root, request, store):
    scopes = (root.get('af_authoring_id') or root.name, root.name)
    fields = ('af_branch_receipts', 'af_free_receipts')
    receipts = [decode(root.get(field, '{}')).get(request['request_id']) for field in fields]
    receipts.extend(_profile_receipts(root, request['request_id']))
    return reservation(store, request, scopes, receipts)


def _profile_receipts(root, identity):
    from ...adapters.authoring.native_profiles import MARKERS
    for muscle in root.af_vcp_system.muscles:
        for field in MARKERS.values():
            row = decode(muscle.get(field, '{}'))
            if row.get('request_id') == identity: yield row

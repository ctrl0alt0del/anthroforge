"""Upgrade ownership fingerprints only when the legacy projection still matches."""
from copy import deepcopy
from ...core.authoring.codec import digest, encode

NEW_VALUES = {'a_point_id', 'b_point_id', 'point_id', 'main_surface_id', 'active_branch_index'}


def legacy_record(record):
    result = deepcopy(record)
    result['values'] = {k: v for k, v in result['values'].items() if k not in NEW_VALUES}
    result['collections'] = {k: [legacy_record(r) for r in rows]
                             for k, rows in result['collections'].items() if k != 'branches'}
    return result


def upgrade_owned_documents(root):
    from .native_scene import root_documents, grouped, owned_record, ownership
    documents = root_documents(root)
    changed = False
    for saved in documents.values():
        try:
            previous = {name: [legacy_record(owned_record(root, name, key)) for key in sorted(keys)]
                        for name, keys in grouped(saved['ids']).items()}
            if saved['fingerprint'] == digest(previous):
                saved['fingerprint'] = ownership(root, saved['ids']); changed = True
        except (KeyError, ValueError):
            continue
    if changed:
        root['af_authoring_documents'] = encode(documents)

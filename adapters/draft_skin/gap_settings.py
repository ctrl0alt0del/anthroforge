try:
    from ...core.draft_skin.gap_settings import record_gap
except ImportError:
    from core.draft_skin.gap_settings import record_gap


def contributor_gap(root, role, entity_id, settings):
    if role == "SCP":
        collection = root.af_scp_system.scps
    else:
        name = {"MUSCLE": "muscles", "FIBER": "fibers", "BLOB": "blobs", "SOFT_TISSUE": "soft_tissues"}[role]
        collection = getattr(root.af_vcp_system, name)
    record = next((item for item in collection if str(item.id) == entity_id), None)
    return record_gap(record, settings)

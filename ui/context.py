from ..core.utils import get_af_root


def get_active_scp(root, context):
    obj = context.active_object
    if obj and obj.get("af_proxy") and obj.get("af_root_name") == root.name:
        scp_id = obj.get("af_scp_id")
        if scp_id:
            for scp in root.af_system.scps:
                if scp.id == scp_id:
                    return scp

    idx = root.af_system.active_scp_index
    if 0 <= idx < len(root.af_system.scps):
        return root.af_system.scps[idx]

    return None


def get_root_or_none(context):
    return get_af_root(context.scene)

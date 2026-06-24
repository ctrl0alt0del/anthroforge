from dataclasses import dataclass

from ..scp_runtime.common import as_id, scp_prop_map
from ..scp_runtime.runtime_state import mirror_status
from ..scp_runtime.tree import children_map


@dataclass(frozen=True)
class ProxyScope:
    owner_id: str
    scp_ids: tuple
    mirror_ids: tuple
    contributors: tuple


@dataclass(frozen=True)
class ProxyContributor:
    scp_id: str
    name: str
    obj: object


def proxy_scope(root, owner_id):
    scp_by_id = scp_prop_map(root)
    ids = _descendants(scp_by_id, as_id(owner_id))
    contributors = tuple(_contributors(scp_by_id, ids))
    mirror_ids = tuple(sid for sid in ids if mirror_status(scp_by_id[sid]) == "TARGET")
    return ProxyScope(as_id(owner_id), tuple(ids), mirror_ids, contributors)


def _descendants(scp_by_id, owner_id):
    kids, out, stack = children_map(scp_by_id), [], [owner_id]
    while stack:
        sid = stack.pop()
        if sid and sid in scp_by_id and sid not in out:
            out.append(sid)
            stack.extend(reversed(kids.get(sid, ())))
    return out


def _contributors(scp_by_id, scp_ids):
    for sid in scp_ids:
        obj = getattr(scp_by_id[sid], "geometry_object_ref", None)
        if obj is not None and getattr(obj, "type", "") == "MESH":
            yield ProxyContributor(sid, _scp_name(scp_by_id[sid], sid), obj)


def _scp_name(scp, sid):
    return str(getattr(scp, "name", "") or sid)

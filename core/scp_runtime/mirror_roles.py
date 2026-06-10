from .common import as_axis, as_id, scp_prop_map
from .runtime_state import mirror_effective_axis, mirror_source_id, mirror_status
from .runtime_state import set_mirror_effective_axis, set_mirror_source_id, set_mirror_status
from .tree import children_map, root_ids, sanitize_parent_links

STATUS_NONE = "NONE"
STATUS_SOURCE = "SOURCE"
STATUS_TARGET = "TARGET"


class MirrorRoleResolver:
    def __init__(self, root):
        self.root = root
        self.scp_by_id = scp_prop_map(root)
        self.children = children_map(self.scp_by_id)
        self.roles = {}
        self.visited = set()

    def apply(self):
        changed, self.scp_by_id = sanitize_parent_links(self.root, self.scp_by_id)
        self.children = children_map(self.scp_by_id)
        self._resolve_roles()
        return changed | self._commit_roles()

    def _resolve_roles(self):
        for sid in root_ids(self.scp_by_id):
            self._walk(sid, "", "X", set())
        for sid in sorted(self.scp_by_id):
            if sid not in self.visited:
                self._walk(sid, "", "X", set())

    def _walk(self, sid, inherited_source_id, inherited_axis, trail):
        sid = as_id(sid)
        if not sid or sid in trail or sid not in self.scp_by_id:
            return
        self.roles[sid] = self._role_for(sid, inherited_source_id, inherited_axis)
        self.visited.add(sid)
        next_source, next_axis = self._next_role_inputs(sid)
        for child_id in self.children.get(sid, []):
            self._walk(child_id, next_source, next_axis, trail | {sid})

    def _role_for(self, sid, inherited_source_id, inherited_axis):
        scp = self.scp_by_id[sid]
        if bool(getattr(scp, "mirror_enabled", False)):
            return {"status": STATUS_SOURCE, "source_id": sid, "effective_axis": as_axis(getattr(scp, "mirror_axis", "X"))}
        if not bool(getattr(scp, "mirror_inherit_parent", True)):
            return {"status": STATUS_NONE, "source_id": "", "effective_axis": as_axis(getattr(scp, "mirror_axis", "X"))}
        if inherited_source_id:
            return {"status": STATUS_TARGET, "source_id": as_id(inherited_source_id), "effective_axis": as_axis(inherited_axis)}
        return {"status": STATUS_NONE, "source_id": "", "effective_axis": as_axis(getattr(scp, "mirror_axis", "X"))}

    def _next_role_inputs(self, sid):
        role = self.roles[sid]
        return as_id(role.get("source_id", "")), as_axis(role.get("effective_axis", "X"))

    def _commit_roles(self):
        changed = set()
        for scp in self.root.af_scp_system.scps:
            changed |= self._commit_one(scp)
        return changed

    def _commit_one(self, scp):
        sid = as_id(getattr(scp, "id", ""))
        role = self.roles.get(sid, {"status": STATUS_NONE, "source_id": "", "effective_axis": as_axis(getattr(scp, "mirror_axis", "X"))})
        return self._write_role_fields(scp, sid, role)

    def _write_role_fields(self, scp, sid, role):
        changed = set()
        changed |= self._write_field(scp, sid, "mirror_status", as_id(role.get("status", STATUS_NONE)) or STATUS_NONE)
        changed |= self._write_field(scp, sid, "mirror_source_id", as_id(role.get("source_id", "")))
        changed |= self._write_field(scp, sid, "mirror_effective_axis", as_axis(role.get("effective_axis", "X")))
        return changed

    def _write_field(self, scp, sid, key, value):
        if _mirror_value(scp, key) == value:
            return set()
        _set_mirror_value(scp, key, value)
        return {sid}


def apply_scp_mirror_roles(root):
    return MirrorRoleResolver(root).apply()


def _mirror_value(scp, key):
    return {"mirror_status": mirror_status, "mirror_source_id": mirror_source_id, "mirror_effective_axis": mirror_effective_axis}[key](scp)


def _set_mirror_value(scp, key, value):
    {"mirror_status": set_mirror_status, "mirror_source_id": set_mirror_source_id, "mirror_effective_axis": set_mirror_effective_axis}[key](scp, value)

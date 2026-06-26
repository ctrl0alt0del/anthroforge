from dataclasses import dataclass

import bmesh

from .consts import ATTR_SLOT, ATTR_VERTEX, FLAG, SIDE_KEY
from .session import proxy_sources


@dataclass(frozen=True)
class ProxyVertexPick:
    scp_id: str = ""
    vertex_index: int = -1
    proxy_index: int = -1
    signature: str = ""
    side: str = ""


def selected_proxy_vertices(context):
    obj, error = _edit_proxy(context)
    if error:
        return (), error
    picks = _selected_picks(obj)
    if not picks:
        return (), "Select one or more proxy vertices."
    return ((), "Selected proxy vertices are missing provenance.") if any(p.scp_id == "" for p in picks) else (picks, "")


def _edit_proxy(context):
    obj = None if context is None else getattr(context, "active_object", None)
    if obj is None or not obj.get(FLAG):
        return None, "Switch to proxy view and edit a proxy mesh."
    if getattr(context, "mode", "") != "EDIT_MESH":
        return None, "Enter Edit Mode on the proxy mesh."
    return (None, "Multi-object edit mode is not supported.") if len(tuple(getattr(context, "objects_in_mode", ()) or (obj,))) > 1 else (obj, "")


def _selected_picks(obj):
    bm = bmesh.from_edit_mesh(obj.data)
    slot = bm.verts.layers.int.get(ATTR_SLOT)
    vertex = bm.verts.layers.int.get(ATTR_VERTEX)
    bm.verts.ensure_lookup_table()
    verts = _ordered_selected_verts(bm)
    return [] if slot is None or vertex is None else [_pick_for_vert(obj, vert, slot, vertex) for vert in verts]


def _ordered_selected_verts(bm):
    history = _history_selected_verts(bm)
    seen = {vert.index for vert in history}
    return history + [vert for vert in bm.verts if vert.select and vert.index not in seen]


def _history_selected_verts(bm):
    return [elem for elem in bm.select_history if isinstance(elem, bmesh.types.BMVert) and elem.select]


def _pick_for_vert(obj, vert, slot, vertex):
    row = _source_row(obj, vert[slot])
    return ProxyVertexPick(row.get("scp_id", ""), int(vert[vertex]), int(vert.index), str(row.get("signature", "") or ""), str(obj.get(SIDE_KEY, "") or ""))


def _source_row(obj, slot):
    rows = proxy_sources(obj)
    return next((row for row in rows if int(row.get("slot", -1)) == int(slot)), {})

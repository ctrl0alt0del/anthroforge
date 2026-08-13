from .drivers import get_registered_entity_types


def dirty_start_nodes(dirty):
    return {(et, eid) for et, ids in dict(dirty or {}).items() for eid in set(ids or set())}


def _non_source_ids(gate_meta):
    payload = dict((gate_meta or {}).get("payload", {}) or {})
    raw = dict(payload.get("non_source_ids_by_type", {}) or {})
    return {str(k): {str(x) for x in set(v or set())} for k, v in raw.items()}


def source_start_nodes(starts, gate_meta):
    blocked = _non_source_ids(gate_meta)
    return {node for node in set(starts or set()) if _source_allowed(node, blocked, gate_meta)}


def _source_allowed(node, blocked, gate_meta):
    if str(node[1]) in blocked.get(str(node[0]), set()):
        return False
    return not (_fiber_update_is_local(node, gate_meta) or _selection_is_local(node, gate_meta))


def _fiber_update_is_local(node, gate_meta):
    meta = dict(gate_meta or {})
    aspects = set(dict(meta.get("dirty_aspects", {}) or {}).get("FIBER", ()) or ())
    event = str(meta.get("event_type", "") or "").upper()
    return str(node[0]) == "FIBER" and event == "FIBER_UPDATE" and bool(aspects)


def _selection_is_local(node, gate_meta):
    event = str(dict(gate_meta or {}).get("event_type", "") or "").upper()
    return event == "SELECTION"


def impact_sets(impacted):
    out = {et: set() for et in get_registered_entity_types()}
    for et, eid in set(impacted or set()):
        if et in out:
            out[et].add(eid)
    return out


def merge_impacts(base, extra):
    for et in set(base.keys()) | set(extra.keys()):
        base.setdefault(et, set())
        base[et] |= set(extra.get(et, set()) or set())


def compute_impacted_sets(graph, dirty, gate_meta=None):
    starts = dirty_start_nodes(dirty)
    sources = source_start_nodes(starts, gate_meta)
    impacted = graph.downstream_entities(sources) if sources else set()
    return impact_sets(impacted | starts)


def expand_constraint_impacts(graph, impacted_sets, constraint_impacts, gate_meta=None):
    starts = source_start_nodes(dirty_start_nodes(constraint_impacts), gate_meta)
    if not starts:
        return impacted_sets
    merge_impacts(impacted_sets, impact_sets(graph.downstream_entities(starts) | starts))
    return impacted_sets

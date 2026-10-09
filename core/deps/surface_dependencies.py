"""Dependency planning for layered geometry consumers."""
from .runtime_graph import RuntimeGraph, tarjan_scc
from .adapters import build_runtime_graph

GEOMETRY = ('FIBER', 'FIBER_SURFACE', 'MUSCLE', 'BLOB', 'SOFT_TISSUE')


def graph_for(root):
    graph = RuntimeGraph(); build_runtime_graph(root, graph)
    return graph


def waves(graph, selected):
    pending = set(selected); adjacency = graph.entity_adjacency()
    while pending:
        blocked = {child for parent in pending for child in adjacency.get(parent, ())}
        ready = tuple(sorted(pending - blocked))
        if not ready: raise ValueError('Cyclic surface attachment dependency: ' + repr(sorted(pending)))
        yield ready
        pending.difference_update(ready)


def require_acyclic(root):
    graph = graph_for(root); adjacency = graph.entity_adjacency()
    cycles = [group for group in tarjan_scc(adjacency) if len(group) > 1]
    if cycles: raise ValueError('Cyclic surface attachment dependency: ' + repr(cycles[0]))
    return graph


def has_muscle_parents(root):
    try: from ..vcp.attachment_surface import muscle_backed
    except ImportError: from core.vcp.attachment_surface import muscle_backed
    return any(muscle_backed(f) for f in root.af_vcp_system.fibers)


def parents(graph):
    result = {}
    for parent, children in graph.entity_adjacency().items():
        for child in children: result.setdefault(child, set()).add(parent)
    return result


def _stacking_edges(root, graph):
    for row in stacking_records(root):
        underlying, covering = _stack_order(row)
        if underlying and covering and underlying[0] != covering[0]:
            graph.add_entity_edge(('MUSCLE', underlying[0]), ('MUSCLE', covering[0]))


def stacking_records(root):
    if not hasattr(root, 'get'): return ()
    try:
        from ..muscle_pairs.configuration import read
        from ..muscle_relationships import store
    except ImportError:
        from core.muscle_pairs.configuration import read
        from core.muscle_relationships import store
    if not read(root)['stacking']: return ()
    document = store.read(root) or {}
    return tuple(row for row in document.get('records', {}).values() if row.get('state') == 'active')


def stacking_targets(root):
    return {tuple(_stack_order(row)[1][:2]) for row in stacking_records(root) if _stack_order(row)[1]}


def stacking_signature(root):
    return tuple(sorted(repr(_stack_order(row)) for row in stacking_records(root)))


def _stack_order(row):
    try: from ..muscle_relationships.identity import domain_key
    except ImportError: from core.muscle_relationships.identity import domain_key
    order = row.get('effective_order') or row
    a, b = order.get('underlying'), order.get('covering')
    return (domain_key(a) if isinstance(a, dict) else a, domain_key(b) if isinstance(b, dict) else b)


def consumers(root, kind, identity):
    return tuple(sorted(graph_for(root).entity_adjacency().get((kind, identity), ())))

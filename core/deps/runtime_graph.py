from collections import defaultdict, deque

from .types import Edge


class RuntimeGraph:
    def __init__(self):
        self.ports = {}
        self.edges = []
        self._entity_edges = defaultdict(set)  # (etype,eid) -> {(etype,eid)}

    def add_port(self, port):
        self.ports[(port.entity_type, port.entity_id, port.port_key, port.phase, port.mutability)] = port
        return port

    def add_edge(self, edge):
        if not isinstance(edge, Edge):
            return
        self.edges.append(edge)
        s = (edge.src.entity_type, edge.src.entity_id)
        d = (edge.dst.entity_type, edge.dst.entity_id)
        self._entity_edges[s].add(d)

    def add_entity_edge(self, src_entity, dst_entity):
        self._entity_edges[src_entity].add(dst_entity)

    def downstream_entities(self, start_entities):
        seen = set(start_entities or [])
        q = deque(start_entities or [])
        while q:
            cur = q.popleft()
            for nxt in self._entity_edges.get(cur, ()):
                if nxt in seen:
                    continue
                seen.add(nxt)
                q.append(nxt)
        return seen

    def entity_adjacency(self):
        return self._entity_edges


def tarjan_scc(adjacency):
    index = 0
    indices = {}
    low = {}
    stack = []
    on_stack = set()
    sccs = []

    def strongconnect(v):
        nonlocal index
        indices[v] = index
        low[v] = index
        index += 1
        stack.append(v)
        on_stack.add(v)

        for w in adjacency.get(v, ()):
            if w not in indices:
                strongconnect(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], indices[w])

        if low[v] == indices[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                comp.append(w)
                if w == v:
                    break
            sccs.append(comp)

    for v in adjacency.keys():
        if v not in indices:
            strongconnect(v)

    return sccs


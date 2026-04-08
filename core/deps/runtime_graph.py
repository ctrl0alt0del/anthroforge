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
    ctx = _TarjanContext(adjacency)
    return ctx.run()


class _TarjanContext:
    def __init__(self, adjacency):
        self.adjacency = adjacency
        self.index = 0
        self.indices = {}
        self.low = {}
        self.stack = []
        self.on_stack = set()
        self.sccs = []

    def _visit(self, v):
        self.indices[v] = self.index
        self.low[v] = self.index
        self.index += 1
        self.stack.append(v)
        self.on_stack.add(v)

    def _visit_neighbor(self, v, w):
        if w not in self.indices:
            self._strongconnect(w)
            self.low[v] = min(self.low[v], self.low[w])
            return
        if w in self.on_stack:
            self.low[v] = min(self.low[v], self.indices[w])

    def _pop_component(self, v):
        comp = []
        while True:
            w = self.stack.pop()
            self.on_stack.remove(w)
            comp.append(w)
            if w == v:
                return comp

    def _strongconnect(self, v):
        self._visit(v)
        for w in self.adjacency.get(v, ()):
            self._visit_neighbor(v, w)
        if self.low[v] == self.indices[v]:
            self.sccs.append(self._pop_component(v))

    def run(self):
        for v in self.adjacency.keys():
            if v not in self.indices:
                self._strongconnect(v)
        return self.sccs

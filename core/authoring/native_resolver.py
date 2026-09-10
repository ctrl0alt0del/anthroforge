"""Legacy projection plus independent allowed-area membership validation."""
import numpy as np
from dataclasses import replace
from .regions import RegionResolver
from .errors import require
from .regions import RegionEvaluator
from .clipping import point_in_polygon
from .references import lookup
from .codec import digest


class DomainResolver(RegionResolver):
    def __init__(self, ir, document, snapshot, inventory, picker=None):
        super().__init__(ir['document'], snapshot)
        evaluator = RegionEvaluator(document, inventory)
        self.domains = resolved_domains(evaluator, ir['domains'], document)
        self.picker, self.bindings = picker, {}

    def point(self, name, at=(), offset=0.):
        from .attachment_binding import capture
        anchor = super().point(name, at, offset)
        key = (name, tuple(at))
        if key not in self.bindings:
            value = capture(self.geometry(name), anchor.surface, anchor.normal)
            self.bindings[key] = (tuple(value['tri_vidx']), tuple(value['tri_weights']))
        return self.checked_anchor(name, replace(anchor, surface_binding=self.bindings[key]))

    def checked_anchor(self, name, anchor):
        domain = self.domains[name]
        require(anchor.owner == domain['owner'], 'ATTACHMENT_INSTANCE_MISMATCH')
        polygons = [np.asarray(p) for p in domain['polygons']]
        require(any(point_in_polygon(anchor.surface, p, 1e-5) for p in polygons), 'SAMPLE_OUTSIDE_ALLOWED_REGION', name)
        return anchor

    def direct_anchor(self, name, seed, offset):
        from .charts import position
        from .attachment_binding import nearest_binding
        region = self.document['regions'][name]
        chart = self.frames[region['frame']]
        guess = position(chart, np.asarray(seed))
        binding = self.picker(chart['mesh'].id, guess) if self.picker else nearest_binding(self.geometry(name), guess)
        anchor = self.bound_anchor(name, binding, offset)
        require(np.linalg.norm(np.asarray(anchor.surface)-guess) <= self.measure(region['projection']['search_distance']), 'SNAP_DISTANCE_EXCEEDED', name)
        return anchor

    def geometry(self, name):
        mesh = self.frames[self.document['regions'][name]['frame']]['mesh']
        return dict(vertices=mesh.vertices, triangles=mesh.triangles, matrix=mesh.matrix)

    def bound_anchor(self, name, binding, offset):
        from .attachment_binding import resolve
        from .model import Anchor
        mesh = self.frames[self.document['regions'][name]['frame']]['mesh']
        point, normal = resolve(self.geometry(name), binding)
        saved = (tuple(binding['tri_vidx']), tuple(binding['tri_weights']))
        anchor = Anchor(mesh.id, tuple(point+normal*offset), tuple(normal), tuple(point), offset, saved)
        return self.checked_anchor(name, anchor)


def resolved_domains(evaluator, references, document):
    cache, result = {}, {}
    for key, ref in references.items():
        region = lookup(document, ref)
        identity = digest({k: region[k] for k in ('frame', 'owner', 'reference_pose', 'query')})
        if identity not in cache:
            cache[identity] = evaluator.evaluate(ref)
        result[key] = dict(cache[identity], reference=ref, definition_digest=digest(region))
    return result

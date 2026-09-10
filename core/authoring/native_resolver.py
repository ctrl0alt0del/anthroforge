"""Legacy projection plus independent allowed-area membership validation."""
import numpy as np
from .regions import RegionResolver
from .errors import require
from .regions import RegionEvaluator
from .clipping import point_in_polygon
from .references import lookup
from .codec import digest


class DomainResolver(RegionResolver):
    def __init__(self, ir, document, snapshot, inventory):
        super().__init__(ir['document'], snapshot)
        evaluator = RegionEvaluator(document, inventory)
        self.domains = resolved_domains(evaluator, ir['domains'], document)

    def point(self, name, at=(), offset=0.):
        anchor = super().point(name, at, offset)
        return self.checked_anchor(name, anchor)

    def checked_anchor(self, name, anchor):
        domain = self.domains[name]
        require(anchor.owner == domain['owner'], 'ATTACHMENT_INSTANCE_MISMATCH')
        polygons = [np.asarray(p) for p in domain['polygons']]
        require(any(point_in_polygon(anchor.surface, p, 1e-5) for p in polygons), 'SAMPLE_OUTSIDE_ALLOWED_REGION', name)
        return anchor

    def direct_anchor(self, name, seed, offset):
        from .regions import project
        from .model import Anchor
        region = dict(self.document['regions'][name], definition=dict(kind='point', seed=seed))
        point, normal, owner = project(region, self.frames[region['frame']], self.triangles[region['frame']], (), self)
        anchor = Anchor(owner, tuple(point+normal*offset), tuple(normal), tuple(point), offset)
        return self.checked_anchor(name, anchor)

    def bound_anchor(self, name, binding, offset):
        from .attachment_binding import resolve
        from .model import Anchor
        mesh = self.frames[self.document['regions'][name]['frame']]['mesh']
        geometry = dict(vertices=mesh.vertices, triangles=mesh.triangles, matrix=mesh.matrix)
        point, normal = resolve(geometry, binding)
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

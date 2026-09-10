"""Shared projected sampling and exact or bounded anatomical surface domains."""
import numpy as np
from time import perf_counter
from . import charts, trims, contact, sheets, clipping, substrate
from .errors import AuthoringError, require
from .geometry import normalized, ray_hits, triangles, face_normals
from .model import Anchor, Budget, Registry
from .codec import digest
from .references import lookup


class RegionResolver:
    def __init__(self, document, snapshot, contacts=None):
        self.document, self.snapshot = document, snapshot
        self.contacts = contacts or contact
        bound = charts.targets(document, snapshot)
        self.frames = {key: charts.frame(value, bound[value["owner"]]) for key, value in document["frames"].items()}
        self.cache = {}
        self.deadline = None
        self.triangles = {key: triangles(value["mesh"]) for key, value in self.frames.items()}

    def measure(self, value, references=None):
        return charts.length(value, self.document, self.frames, references)

    def point(self, name, at=(), offset=0.):
        self.check_budget()
        key = (name, tuple(at))
        if key not in self.cache:
            self.cache[key] = self._project(name, at)
        point, normal, owner = self.cache[key]
        return Anchor(owner, tuple(point + normal * offset), tuple(normal), tuple(point), offset)

    def check_budget(self):
        require(self.deadline is None or perf_counter() < self.deadline,"TOTAL_BUDGET_EXHAUSTED")

    def _project(self, name, at):
        region = self.document["regions"][name]
        try:
            self._budget(name, region)
            return project(region, self.frames[region["frame"]], self.triangles[region["frame"]], at, self)
        except AuthoringError as error:
            error.pointer = "/regions/" + name
            error.args = (str(error) + "; intrinsic coordinate=" + str(list(at)),)
            error.message = str(error)
            raise

    def _budget(self, name, region):
        count = sum(key[0] == name for key in self.cache)
        require(count < region["projection"]["max_samples"], "REGION_SAMPLE_BUDGET")

    def resolve(self, name):
        region = self.document["regions"][name]
        kind = region["definition"]["kind"]
        if kind == "point":
            self.point(name)
        elif kind == "curve":
            count = len(region["definition"]["seeds"]) - int(not region["definition"]["closed"])
            for i in range(count):
                refine_edge(self, name, (i/count,), ((i+1)/count,))
        elif region["definition"].get("trim_uv"):
            trims.resolve(self,name,region["definition"]["trim_uv"])
        else:
            refine_patch(self, name, (0., 0.), (1., 1.))
        return [dict(at=list(at), point=list(value[0]), normal=list(value[1]), owner=value[2])
                for (region_id, at), value in self.cache.items() if region_id == name]


def project(region, chart, tris, at, resolver):
    results = [project_one(region,chart,tris,at,resolver,spec) for spec in sheets.specifications(region["projection"],at)]
    return sheets.joined(results,resolver.measure(region["projection"]["max_surface_error"]))


def project_one(region, chart, tris, at, resolver, spec):
    point = charts.position(chart, charts.seed(region["definition"], at))
    direction = normalized(chart["linear"] @ spec["direction_in_frame"])
    expected = normalized(chart["normal"] @ spec["expected_normal_in_frame"])
    distance = resolver.measure(spec["search_distance"])
    hits = ray_hits(tris, point - direction * distance, direction, 2 * distance)
    normals = face_normals(tris)
    normals *= np.sign(np.linalg.det(chart['mesh'].matrix[:3, :3]))
    valid = [hit for hit in hits if normals[hit[1]] @ expected >= spec["min_normal_dot"]]
    unique = deduplicate(valid, max(1e-10, distance * 1e-8))
    _, index, result = sheets.select(unique,point,spec,resolver)
    return result, normals[index], chart["mesh"].id


def deduplicate(hits, epsilon):
    unique = []
    for hit in sorted(hits, key=lambda item: item[0]):
        if not unique or abs(hit[0] - unique[-1][0]) > epsilon:
            unique.append(hit)
    return unique


def refine_edge(resolver, name, first, last, depth=0):
    middle = tuple((np.asarray(first) + last) / 2)
    a, b, m = [resolver.point(name, at) for at in (first, last, middle)]
    error = np.linalg.norm(np.asarray(m.point) - (np.asarray(a.point) + b.point) / 2)
    limit = resolver.measure(resolver.document["regions"][name]["projection"]["max_surface_error"])
    require(np.dot(a.normal, b.normal) > 0, "REGION_DISCONTINUOUS")
    if error > limit:
        require(depth < 16, "REGION_DISCONTINUOUS")
        refine_edge(resolver, name, first, middle, depth + 1)
        refine_edge(resolver, name, middle, last, depth + 1)


def refine_patch(resolver, name, low, high, depth=0):
    x, y = low
    X, Y = high
    corners = [(x, y), (X, y), (X, Y), (x, Y)]
    middle = ((x+X)/2, (y+Y)/2)
    rows = [resolver.point(name, at) for at in corners]
    center = resolver.point(name, middle)
    error = np.linalg.norm(center.point - np.mean([row.point for row in rows], axis=0))
    for first, last in zip(corners, corners[1:] + corners[:1]):
        refine_edge(resolver, name, first, last)
    limit = resolver.measure(resolver.document["regions"][name]["projection"]["max_surface_error"])
    if error > limit:
        require(depth < 12, "REGION_DISCONTINUOUS")
        subdivide_patch(resolver, name, low, high, depth)


def subdivide_patch(resolver, name, low, high, depth):
    x, y = low
    X, Y = high
    m, n = (x+X)/2, (y+Y)/2
    for a, b in [((x,y),(m,n)), ((m,y),(X,n)), ((x,n),(m,Y)), ((m,n),(X,Y))]:
        refine_patch(resolver, name, a, b, depth+1)


class RegionEvaluator:
    def __init__(self, document, inventory, budget=None):
        self.document, self.inventory = document, inventory
        self.budget, self.active, self.limitations = budget or Budget(), set(), set()
        self.operators = operators(self)

    def evaluate(self, reference):
        region = lookup(self.document, reference)
        chart = substrate.frame(self.document, self.inventory, region['frame'])
        require(region['owner'] == lookup(self.document, region['frame'])['owner'], 'REGION_OWNER_MISMATCH')
        require(region['reference_pose'] == self.inventory['reference_pose'], 'REFERENCE_POSE_MISMATCH')
        self.active.add(reference)
        try:
            inside, _ = self.partition(list(substrate.surface(chart)), region['query'], chart)
        finally:
            self.active.remove(reference)
        polygons = [substrate.world(chart, p).tolist() for p in inside]
        return dict(reference=reference, owner=chart['owner']['instance_id'], polygons=polygons, area=sum(clipping.area(np.array(p)) for p in polygons), limitations=sorted(self.limitations), definition_digest=digest(region))

    def partition(self, polygons, query, chart):
        self.budget.check()
        if query['kind'] == 'surface_patch':
            from .surface_patch import partition
            self.limitations.add('Visual patch follows triangle correspondence; changed topology requires rebinding and changed geometry invalidates anatomical review.')
            return partition(polygons, query, chart, self.budget)
        return self.operators.get(query['kind']+'.v1')(polygons, query, chart)

    def named(self, polygons, query, chart):
        return self.reference(polygons, query['ref'], chart)

    def connected(self, polygons, query, chart):
        selected, rejected = self.partition(polygons, query['query'], chart)
        kept = clipping.connected(selected, query['seed'], query['tolerance'])
        return kept, rejected + [p for p in selected if not any(p is x for x in kept)]

    def spatial(self, polygons, query, chart):
        return self.selector(polygons, query['selector'])

    def boolean(self, polygons, query, chart):
        inside, outside = self.partition(polygons, query['operands'][0], chart)
        for operand in query['operands'][1:]:
            if query['kind'] == 'union':
                add, outside = self.partition(outside, operand, chart)
                inside += add
            else:
                a, b = self.partition(inside, operand, chart)
                inside, outside = (a, outside+b) if query['kind'] == 'intersection' else (b, outside+a)
        return inside, outside

    def reference(self, polygons, reference, chart):
        require(reference not in self.active, 'DEPENDENCY_CYCLE', reference)
        region = lookup(self.document, reference)
        other = substrate.frame(self.document, self.inventory, region['frame'])
        require(other['owner']['instance_id'] == chart['owner']['instance_id'], 'REGION_OWNER_MISMATCH')
        self.active.add(reference)
        try:
            if np.array_equal(other['linear'], chart['linear']) and np.array_equal(other['origin'], chart['origin']):
                return self.partition(polygons, region['query'], other)
            transformed = [substrate.coordinates(other, substrate.world(chart, p)) for p in polygons]
            a, b = self.partition(transformed, region['query'], other)
            return tuple([substrate.coordinates(chart, substrate.world(other, p)) for p in group] for group in (a, b))
        finally:
            self.active.remove(reference)

    def selector(self, polygons, selector):
        if selector['kind'] == 'box':
            return clipping.partition(polygons, clipping.box_planes(selector['low'], selector['high']), self.budget)
        radii, center = np.asarray(selector['radii']), np.asarray(selector['center'])
        require(np.all(radii > 0), 'SELECTOR_INVALID_RADII')
        self.limitations.add('Curved boundary sampled at subdivision depth '+str(selector['depth'])+'; subcell features may be missed.')
        return clipping.curved(polygons, lambda p: np.linalg.norm((p-center)/radii)-1, selector['depth'], self.budget, 1/min(radii))

    def anatomical(self, polygons, query, chart):
        if query['kind'] == 'half_space':
            landmark = lookup(self.document, query['landmark'])
            other = substrate.frame(self.document, self.inventory, landmark['frame'])
            point = substrate.coordinates(chart, substrate.world(other, landmark['q']))
            normal = np.asarray(query['normal'])
            require(np.linalg.norm(normal) > 0, 'PLANE_NORMAL_INVALID')
            return clipping.partition(polygons, [(normal, float(point @ normal))], self.budget)
        guide = substrate.control(self.document, self.inventory, query['control'])
        points = substrate.coordinates(chart, guide['points'])
        require(0 <= query['interval'][0] < query['interval'][1] <= 1 and query['radius'] > 0, 'GUIDE_BAND_INVALID')
        self.limitations.add('Guide band uses bounded sampled reference-pose coordinates.')
        return clipping.curved(polygons, lambda p: band_distance(points, p, query, guide['reference_points']), query['depth'], self.budget)


def band_distance(points, point, query, reference=None):
    t, distance = substrate.guide_material(points, point, reference)
    return max(query['interval'][0]-t, t-query['interval'][1], distance-query['radius'])


def operators(evaluator):
    registry = Registry()
    for kind in ('union', 'intersection', 'difference'):
        registry.add(kind+'.v1', evaluator.boolean)
    for kind, handler in [('region', evaluator.named), ('connected', evaluator.connected), ('selector', evaluator.spatial), ('half_space', evaluator.anatomical), ('guide_interval', evaluator.anatomical)]:
        registry.add(kind+'.v1', handler)
    return registry

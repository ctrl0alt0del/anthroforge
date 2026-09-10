"""Recipe strategies compile anatomical roles to native fiber plans."""
import numpy as np
from .charts import footprint
from .errors import require
from .model import FiberPlan


def fibers(document, muscle_id, resolver, extra=()):
    muscle = document["muscles"][muscle_id]
    construction = document["recipes"][muscle["recipe"]]["construction"]
    if construction["kind"] == "closed_loft":
        require(len(construction["loops"]) <= 128, "FIBER_COUNT_BUDGET")
        return tuple(closed_fiber(muscle_id, muscle, construction, loop, resolver) for loop in construction["loops"])
    coordinates = sorted(set(construction["fiber_u"]) | set(extra))
    if construction.get('boundary_conformance'):
        from .conformance import samples
        coordinates = samples(document, muscle_id, resolver, coordinates)
    require(len(coordinates) <= 128, "FIBER_COUNT_BUDGET")
    return tuple(open_fiber(muscle_id, muscle, construction, u, resolver) for u in coordinates)


def anchor(muscle, role, at, offset, resolver):
    region = muscle["region_bindings"][role]["region"]
    check_trim(resolver.document["regions"][region], at)
    return resolver.point(region, at, resolver.measure(offset))


def open_fiber(name, muscle, construction, u, resolver):
    stations = construction["stations"]
    anchors = tuple(anchor(muscle, s["region_role"], footprint(s["sample"], u), s["offset"], resolver) for s in stations)
    return FiberPlan(name + ".u" + format(u, ".12g"), u, anchors, tuple(s["s"] for s in stations),
                     construction["nodes_per_fiber"], False)


def closed_fiber(name, muscle, construction, loop, resolver):
    specs = [loop["anchors"][s["id"]] for s in construction["stations"]]
    anchors = tuple(anchor(muscle, s["region_role"], location(s["at"]), s["offset"], resolver) for s in specs)
    return FiberPlan(name + ".u" + str(loop["u"]), loop["u"], anchors,
                     tuple(s["s"] for s in construction["stations"]), construction["nodes_per_fiber"], True)


def location(spec):
    return () if spec["kind"] == "point" else (spec["t"],) if spec["kind"] == "curve" else tuple(spec["uv"])


def check_trim(region, at):
    polygon = region["definition"].get("trim_uv")
    if polygon is None:
        return
    inside, x, y = False, *at
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        cross = (x-a[0])*(b[1]-a[1]) - (y-a[1])*(b[0]-a[0])
        if abs(cross) < 1e-10 and min(a[0],b[0])-1e-10 <= x <= max(a[0],b[0])+1e-10 and min(a[1],b[1])-1e-10 <= y <= max(a[1],b[1])+1e-10:
            return
        if (a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            inside = not inside
    require(inside, "FOOTPRINT_OUTSIDE_REGION")


def material_samples(stations, count, closed):
    markers = list(stations) + ([1.] if closed else [])
    widths = np.diff(markers)
    edges = count if closed else count - 1
    require(edges >= len(widths), "INSUFFICIENT_STATION_SAMPLES")
    allocation = np.ones(len(widths), dtype=int)
    for _ in range(edges - len(widths)):
        index = int(np.argmax(widths / allocation))
        allocation[index] += 1
    values = [np.linspace(a, b, n+1)[:-1] for a,b,n in zip(markers, markers[1:], allocation)]
    return np.concatenate(values + ([] if closed else [np.array([1.])]))


def corresponding(points, plan):
    values = material_samples(plan.stations, plan.count, plan.closed)
    source_s = material_coordinates(points, plan)
    source = np.vstack((points, points[0])) if plan.closed else points
    if plan.closed:
        source_s = np.r_[source_s, 1.]
    return np.column_stack([np.interp(values, source_s, source[:,axis]) for axis in range(3)]), values


def material_coordinates(points, plan):
    points = np.asarray(points)
    anchors = np.asarray([a.point for a in plan.anchors])
    pins = match_pins(points, anchors, plan.closed)
    source_s = []
    markers = list(plan.stations) + ([1.] if plan.closed else [])
    for a,b,start,stop in zip(markers, markers[1:], pins, pins[1:]):
        block = points[start:stop+1] if stop < len(points) else np.vstack((points[start:], points[0]))
        spans = np.r_[0., np.cumsum(np.linalg.norm(np.diff(block, axis=0), axis=1))]
        require(spans[-1] > 1e-12, "DEGENERATE_FIBER_SPAN")
        source_s.extend((a + (b-a)*spans/spans[-1])[:-1])
    return np.asarray(source_s if plan.closed else source_s + [1.])


def match_pins(points, anchors, closed):
    pins = [0]
    require(np.linalg.norm(points[0]-anchors[0]) < 1e-4, "SOLVER_ANCHOR_MISMATCH")
    for anchor in anchors[1:]:
        start = pins[-1] + 1
        require(start < len(points), "SOLVER_ANCHOR_MISMATCH")
        index = start + int(np.argmin(np.linalg.norm(points[start:] - anchor, axis=1)))
        require(np.linalg.norm(points[index] - anchor) < 1e-4, "SOLVER_ANCHOR_MISMATCH")
        pins.append(index)
    require(closed or pins[-1] == len(points)-1, "SOLVER_ANCHOR_MISMATCH")
    return pins + ([len(points)] if closed else [])

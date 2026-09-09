"""Region-constrained station curves sampled independently of native fibers."""
import numpy as np
from . import compilation, inflation
from .charts import footprint
from .errors import require


def specification(document, name):
    muscle = document["muscles"][name]
    return document["recipes"][muscle["recipe"]]["construction"].get("boundary_conformance")


def stations(document, name):
    muscle = document["muscles"][name]
    construction = document["recipes"][muscle["recipe"]]["construction"]
    wanted = specification(document,name)["stations"]
    return [s for s in construction["stations"] if s["id"] in wanted]


def target(document, name, station, u, resolver):
    return np.asarray(compilation.anchor(document["muscles"][name],station["region_role"],
                      footprint(station["sample"],u),station["offset"],resolver).point)


def samples(document, name, resolver, initial):
    spec = specification(document,name)
    values = set(float(v) for v in initial)
    tolerance = resolver.measure(spec["max_error"])
    require(tolerance > 0, "BOUNDARY_ERROR_MUST_BE_POSITIVE")
    require(len(values) <= spec["max_samples"], "BOUNDARY_SAMPLE_BUDGET")
    for station in stations(document,name):
        for first,last in zip(sorted(values),sorted(values)[1:]):
            subdivide(document,name,station,resolver,first,last,values,tolerance,spec["max_samples"])
    return np.asarray(sorted(values))


def subdivide(document,name,station,resolver,a,b,values,tolerance,budget,depth=0):
    left,right = [target(document,name,station,u,resolver) for u in (a,b)]
    probes = [a+(b-a)*t for t in (.25,.5,.75)]
    errors = [np.linalg.norm(target(document,name,station,u,resolver)-(left+(right-left)*(u-a)/(b-a))) for u in probes]
    if max(errors) <= tolerance:
        return
    require(depth < 16 and len(values) < budget, "BOUNDARY_SAMPLE_BUDGET", station["id"])
    middle = (a+b)/2
    values.add(middle)
    subdivide(document,name,station,resolver,a,middle,values,tolerance,budget,depth+1)
    subdivide(document,name,station,resolver,middle,b,values,tolerance,budget,depth+1)


def apply(grid,u,s,document,name,resolver,adaptive=True):
    spec = specification(document,name)
    if spec is None:
        return grid,u
    dense = samples(document,name,resolver,u) if adaptive else np.asarray(u)
    result = resample(grid,u,dense)
    for station in stations(document,name):
        column = int(np.argmin(abs(np.asarray(s)-station["s"])))
        wanted = np.asarray([target(document,name,station,x,resolver) for x in dense])
        correction = wanted-result[:,column]
        weight = 1-inflation.smooth(abs(np.asarray(s)-station["s"])/spec["blend_span"])
        result += correction[:,None,:]*weight[None,:,None]
    return result,dense


def resample(grid,u,dense):
    return np.asarray([[[np.interp(x,u,grid[:,j,k]) for k in range(3)]
                         for j in range(grid.shape[1])] for x in dense])

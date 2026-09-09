"""Contact evidence and longitudinal candidates in stable material coordinates."""
import numpy as np


def annotate(result):
    report = result["contact"]
    indices = np.asarray(result["faces"])
    indices = np.vstack((indices[:,:3],indices[:,[0,2,3]]))
    material = np.asarray([(u,s) for u in result["u"] for s in result["s"]])
    report["material_triangles"] = material[indices[report["triangles"]]].tolist()
    report["area_measure"] = "conservative_flagged_triangle_area"
    report["depth_measure"] = "sampled_maximum"
    report["repair_class"] = classify(report["material_triangles"])


def classify(triangles):
    if not len(triangles):
        return "none"
    points = np.asarray(triangles).reshape(-1,2)
    return "boundary_conformance" if np.any((points < 1e-9)|(points > 1-1e-9)) else "interior_support_fiber"


def candidate(result,rejected):
    triangles = result["contact"].get("material_triangles",[])
    values = [row["u"] for row in result["fibers"]]
    scores = {}
    for tri in triangles:
        position = float(np.mean(np.asarray(tri)[:,0]))
        a,b = next(((a,b) for a,b in zip(values,values[1:]) if a <= position <= b),(0.,1.))
        location = round(float(np.clip(position,a+(b-a)*.15,b-(b-a)*.15)),12)
        if min(abs(location-u) for u in values) > 1e-5 and location not in rejected:
            scores[location] = scores.get(location,0)+1
    return max(scores,key=scores.get,default=None)


def covered(before,after):
    old = np.asarray(before.get("material_triangles",[]))
    new = np.asarray(after.get("material_triangles",[]))
    if not len(new):
        return True
    if not len(old):
        return False
    probes = np.concatenate((new,new.mean(1)[:,None]),axis=1).reshape(-1,2)
    return all(inside_union(point,old) for point in probes)


def inside_union(point,triangles):
    edges = np.roll(triangles,-1,axis=1)-triangles
    delta = point-triangles
    cross = edges[:,:,0]*delta[:,:,1]-edges[:,:,1]*delta[:,:,0]
    return bool(np.any(np.all(cross >= -1e-9,axis=1)|np.all(cross <= 1e-9,axis=1)))

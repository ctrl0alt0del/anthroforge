"""Batched native clearance diagnostics; nearest normals are not a volume-inside guarantee."""
import numpy as np
from ..vcp.v2.collision_native import NativeCollisionWorld


def clearance(vertices, quads, samples):
    world = NativeCollisionWorld()
    faces = np.concatenate((quads[:,[0,1,2]],quads[:,[0,2,3]]))
    try:
        world.add(vertices,faces,0,0,False); world.commit()
        nearest, normals, distances, *_ = world.nearest(samples)
        return np.sum((nearest-samples)*normals,axis=1), distances
    finally: world.close()


def annotate(context, result):
    a = context.deformation_reference.arrays; scale = float(np.ptp(a["vertices"],axis=0).max())
    try:
        baseline, _ = clearance(a["vertices"],a["quads"],a["samples"])
        current, distances = clearance(result.vertices,result.quads,context.anatomy_targets)
        result.statistics["anatomy_clearance"] = dict(samples=len(current),negative_samples=int(np.sum(current < -scale*1e-6)),
            reference_negative_samples=int(np.sum(baseline < -scale*1e-6)),minimum=float(current.min()),
            maximum_clearance_loss=float(np.maximum(baseline-current,0).max()),distance_p95=float(np.quantile(distances,.95)),
            interpretation="Nearest-surface normal diagnostic; not a complete skin-anatomy volume intersection check.")
        result.statistics["warnings"].append("Skin-anatomy volume penetration is not fully validated; sampled normal clearance is reported separately.")
    except (RuntimeError,ValueError,OSError) as error:
        result.statistics["anatomy_clearance"] = dict(incomplete=str(error))
        result.statistics["warnings"].append("Skin-anatomy clearance diagnostic unavailable: "+str(error))
    return result

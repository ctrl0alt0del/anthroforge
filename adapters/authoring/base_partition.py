"""Mechanical checks of a repaired pair; anatomy and SCP clearance stay separate."""
from .smooth_quality import combined


def inspect(meshes):
    spatial = combined([dict(native=m) for m in meshes])
    return dict(ready=not spatial['crossing_pairs'] and not spatial['degenerate_triangles'], spatial=spatial,
        anatomical_review='required', bone_clearance='not tested',
        shared_border='coincident geometry; partial borders do not acquire live shared fiber identity',
        complete_intersection_certificate=False)

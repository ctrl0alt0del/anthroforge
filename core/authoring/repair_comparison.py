"""Compare candidates on identical material tessellations to avoid sampling wins."""
import numpy as np
from . import conformance, inflation, contact, contact_repair


def acceptable(before,after,options,tolerance,resolver,version):
    if after is None:
        return False
    if version != "0.3.0":
        return contact.acceptable(before["contact"],after["contact"],options["min_relative_area_reduction"],tolerance)
    u = np.unique(np.r_[before["u"],after["u"]])
    first,last = [report(output,u,tolerance,resolver) for output in (before,after)]
    return contact.acceptable(first,last,options["min_relative_area_reduction"],tolerance)


def report(output,u,tolerance,resolver):
    from .evaluation import evaluate_contact
    if "side_a" in output: return envelope_report(output, u, tolerance, resolver)
    columns = len(output["s"])
    grid = np.asarray(output["inflated"]).reshape(len(output["u"]),columns,3)
    dense = conformance.resample(grid,output["u"],u)
    faces = inflation.faces(len(u),columns,output["fibers"][0]["closed"])
    result = dict(output,u=u,faces=faces.tolist(),contact=evaluate_contact(resolver,dense,faces,tolerance))
    contact_repair.annotate(result)
    result["contact"]["comparison_sampling"] = "common_material_grid"
    return result["contact"]


def envelope_report(output, u, tolerance, resolver):
    from .evaluation import evaluate_contact
    from ..vcp.muscle_envelope_native import compose
    shape = (len(output['u']), len(output['s']), 3)
    a, b = (conformance.resample(np.asarray(output[key]).reshape(shape), output['u'], u).reshape(-1, 3) for key in ('side_a', 'side_b'))
    faces = inflation.faces(len(u), shape[1], False)
    vertices, output_faces, sources, sides = compose(a, b, faces)
    result = dict(output, u=u, faces=faces.tolist(), inflated_sources=sources, face_sides=sides,
                  contact=evaluate_contact(resolver, vertices, output_faces, tolerance))
    contact_repair.annotate(result)
    result['contact']['comparison_sampling'] = 'common_material_grid_both_sides'
    return result['contact']

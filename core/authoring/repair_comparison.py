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
    columns = len(output["s"])
    grid = np.asarray(output["inflated"]).reshape(len(output["u"]),columns,3)
    dense = conformance.resample(grid,output["u"],u)
    faces = inflation.faces(len(u),columns,output["fibers"][0]["closed"])
    result = dict(output,u=u,faces=faces.tolist(),contact=evaluate_contact(resolver,dense,faces,tolerance))
    contact_repair.annotate(result)
    result["contact"]["comparison_sampling"] = "common_material_grid"
    return result["contact"]

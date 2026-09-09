"""Semantic validation for explicit 0.3 capabilities."""
import numpy as np
from .errors import require


def validate(document):
    for recipe in document["recipes"].values():
        construction = recipe["construction"]
        if "boundary_conformance" in construction:
            boundary(construction)
    for region in document["regions"].values():
        projection(region)
    for preset in document["volume_presets"].values():
        require(all(c["metric"] == "normal_height" or c["statistic"] == "max" for c in preset["shape_checks"]),"SECTION_STATISTIC")


def boundary(construction):
    spec = construction["boundary_conformance"]
    stations = {s["id"]:s for s in construction["stations"]}
    require(len(set(spec["stations"])) == len(spec["stations"]), "DUPLICATE_BOUNDARY_STATION")
    require(all(s in stations for s in spec["stations"]), "UNKNOWN_BOUNDARY_STATION")
    positions = sorted(stations[s]["s"] for s in spec["stations"])
    require(all(b-a >= 2*spec["blend_span"] for a,b in zip(positions,positions[1:])), "BOUNDARY_BANDS_OVERLAP")
    require(all(stations[s]["offset"].get("value",0) == 0 and stations[s]["offset"].get("fraction",0) == 0
                for s in spec["stations"]), "BOUNDARY_OFFSET_UNSUPPORTED")


def projection(region):
    spec = region["projection"]
    require(spec["hit_policy"] != "closest_seed" or "selection_margin" in spec, "SHEET_SELECTION_MARGIN_REQUIRED")
    dimension = {"point":0,"curve":1,"patch":2}[region["definition"]["kind"]]
    for chart in spec.get("charts",[]):
        require(len(chart["domain"]) == dimension, "CHART_DIMENSION_MISMATCH")
        require(all(a < b for a,b in chart["domain"]), "EMPTY_CHART_DOMAIN")
        for key in ("direction_in_frame","expected_normal_in_frame"):
            require(abs(np.linalg.norm(chart[key])-1) < 1e-6, "NONUNIT_PROJECTION_VECTOR")


def landmark_basis(spec, vertices):
    points = spec["landmarks_q"]
    extent = vertices.max(0)-vertices.min(0)
    x = (np.asarray(points["x"])-points["origin"])*extent
    other = (np.asarray(points["xy"])-points["origin"])*extent
    z = np.cross(x,other)
    require(np.linalg.norm(x) > 1e-10 and np.linalg.norm(z) > 1e-10, "DEGENERATE_LANDMARK_FRAME")
    x,z = x/np.linalg.norm(x),z/np.linalg.norm(z)
    return np.column_stack((x,np.cross(z,x),z))

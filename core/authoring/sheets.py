"""Explicit local projection charts and bounded seed-relative sheet selection."""
import numpy as np
from .errors import require


def specifications(spec,at):
    if "charts" not in spec:
        return [spec]
    charts = [chart for chart in spec["charts"] if all(a-1e-12 <= t <= b+1e-12 for t,(a,b) in zip(at,chart["domain"]))]
    require(bool(charts), "REGION_CHART_GAP", str(at))
    return [dict(spec,**{k:v for k,v in chart.items() if k != "domain"}) for chart in charts]


def select(hits,point,spec,resolver):
    require(bool(hits),"REGION_NO_HIT",f"No qualified hit at world seed {point.tolist()}")
    if spec["hit_policy"] == "unique":
        require(len(hits) == 1,"REGION_MULTIPLE_HITS",f"{len(hits)} qualified hits")
        return hits[0]
    ordered = sorted(hits,key=lambda h:np.linalg.norm(h[2]-point))
    margin = resolver.measure(spec["selection_margin"])
    require(margin > 0,"SHEET_SELECTION_MARGIN_REQUIRED")
    if len(ordered) > 1:
        gap = np.linalg.norm(ordered[1][2]-point)-np.linalg.norm(ordered[0][2]-point)
        require(gap > margin,"REGION_MULTIPLE_HITS",f"Seed-distance separation {gap:g} <= {margin:g}")
    return ordered[0]


def joined(results,tolerance):
    require(all(np.linalg.norm(a[0]-results[0][0]) <= tolerance and np.dot(a[1],results[0][1]) > 0 for a in results),
            "REGION_CHART_SEAM_MISMATCH")
    return results[0]

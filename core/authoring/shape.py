"""Material cross-section measurements on the default inflated surface."""
import numpy as np
from . import inflation
from .errors import require


def measurements(base,inflated,u,s,config,closed,resolver,refs):
    reports = []
    for check in config["shape_checks"]:
        value = measure(base,inflated,u,s,config,closed,check)
        low,high = [resolver.measure(check[key],refs) for key in ("minimum","maximum")]
        reports.append(dict(metric=check["metric"],s=check["s"],value=value,minimum=low,maximum=high,unit="scene"))
    return reports


def measure(base,inflated,u,s,config,closed,check):
    coordinates = np.unique(np.r_[np.linspace(*check["u_range"],129),[x for x in u if check["u_range"][0]<=x<=check["u_range"][1]]])
    section = np.array([inflation.sample(inflated,u,s,x,check["s"],closed) for x in coordinates])
    if check["metric"] == "section_width":
        return float(np.linalg.norm(section[-1]-section[0]))
    if check["metric"] == "section_arc_length":
        return float(np.linalg.norm(np.diff(section,axis=0),axis=1).sum())
    normal = inflation.normals(base,closed)*(-1 if config["flip_normals"] else 1)
    height = np.einsum("ijk,ijk->ij",inflated-base,normal)
    values = [inflation.sample(np.repeat(height[...,None],3,axis=2),u,s,x,check["s"],closed)[0] for x in coordinates]
    return float(max(values) if check["statistic"] == "max" else np.trapz(values,coordinates)/(coordinates[-1]-coordinates[0])
                 if coordinates[-1] > coordinates[0] else values[0])


def validate(reports):
    for report in reports:
        require(report["minimum"] <= report["value"] <= report["maximum"], "SHAPE_OUT_OF_RANGE",
                f'{report["metric"]} at s={report["s"]}: {report["value"]:g}; expected {report["minimum"]:g}..{report["maximum"]:g}')

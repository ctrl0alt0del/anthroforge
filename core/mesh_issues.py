"""Skin/topology policy: structural contracts block; measured quality does not."""
from dataclasses import asdict
import numpy as np

ISSUE_PROTOCOL = 1
COUNTS = {"source_vertices_outside": "Source vertices outside skin",
          "source_triangles_crossed": "Skin crosses source geometry",
          "protected_gap_violations": "Protected gap constraint violations",
          "preexisting_source_intersections": "Pre-existing source intersections",
          "self_intersections": "Surface self-intersections", "unbound_percent": "Unbound skin vertices (%)",
          "unsupported_components_removed": "Unsupported components removed"}


def require_mesh(vertices, faces, width=None):
    points, polygons = np.asarray(vertices), np.asarray(faces)
    if points.ndim != 2 or points.shape[1] != 3 or not len(points) or not np.isfinite(points).all():
        raise ValueError("Mesh requires nonempty finite XYZ positions.")
    if polygons.ndim != 2 or not len(polygons) or polygons.shape[1] < 3:
        raise ValueError("Mesh requires a nonempty polygon array.")
    if width is not None and polygons.shape[1] != width:
        raise ValueError(f"Consumer requires {width} indices per face.")
    if polygons.dtype.kind not in "iu" or np.any(polygons < 0) or np.any(polygons >= len(points)):
        raise ValueError("Mesh contains invalid vertex indices.")
    if not np.any(np.all(np.diff(np.sort(polygons, axis=1), axis=1) != 0, axis=1)):
        raise ValueError("Mesh has no usable faces.")
    _require_area(points, polygons)


def finding(code, summary, stage, evidence=None, severity="warning"):
    return dict(code=code, summary=summary, details="", stage=stage, severity=severity,
                evidence=evidence or {}, local_key=code)


def quality_findings(report, stats, stage):
    values = [] if report is None else _report_findings(report, stage)
    if report is not None and not report.valid and not values:
        values.append(finding("QUALITY_FAILED", report.message or "Quality checks failed", stage))
    if report is None:
        values.append(finding("QUALITY_UNKNOWN", "Quality has not been verified", stage))
    for name, label in COUNTS.items():
        value = stats.get(name)
        if value is not None and float(value) > 0:
            values.append(finding(name.upper(), f"{label}: {value}", stage, _metric_evidence(name, value, stats)))
    for index, message in enumerate(stats.get("warnings", ())):
        values.append(finding(f"NOTICE_{index}", str(message), stage))
    return values


def _report_findings(report, stage):
    return [finding("QUALITY_" + name.upper(), name.replace("_", " ").capitalize() + " check failed",
                    stage, {"check": name, "message": report.message})
            for name, value in asdict(report).items() if isinstance(value, bool) and not value and name != "valid"]


def annotate(result, stage):
    faces = result.triangles if hasattr(result, "triangles") else result.quads
    require_mesh(result.vertices, faces, 3 if hasattr(result, "triangles") else 4)
    stats = result.statistics
    stats["issue_protocol"] = ISSUE_PROTOCOL
    stats["quality_report"] = None if result.validation is None else asdict(result.validation)
    rows = quality_findings(result.validation, stats, stage)
    rows.extend(_strategy_findings(stats.get("strategy_metrics", {}), stage))
    existing = [row for row in stats.get("issues", ()) if row.get("stage") != stage]
    stats["issues"] = existing + rows
    return result


def restore_report(stats, report_type):
    payload = stats.get("quality_report")
    if not isinstance(payload, dict):
        return None
    try:
        return report_type(**payload)
    except (TypeError, ValueError):
        return None


def _require_area(points, faces):
    for index in range(1, faces.shape[1]-1):
        a = points[faces[:, index]] - points[faces[:, 0]]
        b = points[faces[:, index+1]] - points[faces[:, 0]]
        if np.any(np.cross(a, b) != 0):
            return
    raise ValueError("Mesh has no nonzero-area faces.")


def _metric_evidence(name, value, stats):
    evidence = {name: value}
    if name == "self_intersections":
        evidence.update(face_pairs=stats.get("intersection_witnesses", ()),
                        tessellation=stats.get("intersection_tessellation", "unknown"))
    return evidence


def _strategy_findings(metrics, stage):
    rows = []
    for key in ("no_inversions", "symmetry_ok", "surface_fit_ok"):
        if metrics.get(key) is False:
            rows.append(finding("UPDATE_"+key.upper(), "Update " + key.replace("_", " ") + " check failed", stage, metrics))
    if metrics.get("quality_warning"):
        rows.append(finding("UPDATE_QUALITY", metrics["quality_warning"], stage))
    return rows

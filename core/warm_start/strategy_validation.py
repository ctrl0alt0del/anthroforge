"""Shared publication checks, independent of the selected update algorithm."""
import numpy as np
from dataclasses import replace
from ..topology.validation import validate_topology
from .metrics import symmetry_error
from .topology_solver import evaluate_skin_binding, validate_warm_topology


def validate_candidate(context, candidate, options):
    from ..mesh_issues import require_mesh
    _identity(context, candidate)
    require_mesh(candidate.vertices, context.topology.quads, 4)
    _bindings(context, candidate)
    report = validate_topology(candidate.vertices, context.topology.quads, _persistent_quality(context))
    warm = validate_warm_topology(context.topology.vertices, context.topology.quads, candidate.vertices)
    metrics = _metrics(context, candidate)
    error = report.message if not report.valid else warm.message if not warm.valid else ""
    metrics["no_inversions"] = warm.no_inversions
    _quality_metrics(context, options, metrics, error)
    report = _quality_report(report, metrics)
    return report, metrics


def _identity(context, candidate):
    points, old = np.asarray(candidate.vertices), context.topology
    if points.shape != np.asarray(old.vertices).shape or not np.isfinite(points).all():
        raise ValueError("Topology update changed vertex count or returned nonfinite positions.")
    if not np.array_equal(candidate.vertex_ids, np.arange(len(old.vertices))):
        raise ValueError("Topology update changed vertex identities or order.")


def _bindings(context, candidate):
    count, skin, guide = len(candidate.vertices), candidate.skin_binding, candidate.guide_binding
    if skin is None or guide is None:
        raise ValueError("Topology update did not return persistent bindings.")
    _skin_binding(skin, count, len(context.after_skin.triangles))
    arrays = (guide.guide_indices, guide.rows, guide.parameters)
    if any(np.asarray(value).shape != (count,) for value in arrays):
        raise ValueError("Topology guide binding size does not match vertex identities.")
    if not np.isfinite(guide.parameters).all():
        raise ValueError("Topology guide bindings contain nonfinite parameters.")


def _skin_binding(binding, count, triangles):
    indices, weights, offsets = map(np.asarray, (binding.triangle_indices, binding.barycentric, binding.offsets))
    if indices.shape != (count,) or weights.shape != (count, 3) or offsets.shape != (count,):
        raise ValueError("Topology skin binding size does not match vertex identities.")
    if indices.dtype.kind not in "iu" or np.any(indices < 0) or np.any(indices >= triangles):
        raise ValueError("Topology skin bindings reference missing triangles.")
    if not np.isfinite(weights).all() or not np.isfinite(offsets).all():
        raise ValueError("Topology skin bindings contain nonfinite values.")
    if np.any(weights < -1e-6) or not np.allclose(weights.sum(axis=1), 1.0, atol=1e-5):
        raise ValueError("Topology skin bindings contain invalid barycentric coordinates.")


def _metrics(context, candidate):
    skin, plane = context.after_skin, context.capture.plane
    bound = evaluate_skin_binding(candidate.skin_binding, skin.vertices, skin.triangles)
    bare = replace(candidate.skin_binding, offsets=np.zeros(len(candidate.vertices)))
    surface = evaluate_skin_binding(bare, skin.vertices, skin.triangles)
    errors = np.linalg.norm(np.asarray(candidate.vertices) - surface, axis=1)
    symmetry = symmetry_error(candidate.vertices, plane.origin, plane.normal)["max"] if plane else 0.0
    return {"binding_surface_max": float(errors.max(initial=0)),
            "binding_surface_p95": float(np.quantile(errors, .95)), "symmetry_max": symmetry,
            "binding_residual_max": float(np.linalg.norm(candidate.vertices - bound, axis=1).max(initial=0))}


def _quality_metrics(context, options, metrics, error):
    scale = max(float(np.ptp(context.topology.vertices, axis=0).max()), 1.0)
    metrics["symmetry_ok"] = metrics["symmetry_max"] <= 1e-6 * scale
    metrics["surface_fit_ok"] = options.maximum_surface_error is None or metrics["binding_surface_max"] <= options.maximum_surface_error
    if not metrics["symmetry_ok"]:
        error = "Topology update violates the requested symmetry plane."
    if not metrics["surface_fit_ok"]:
        error = "Topology update exceeds the shared surface-fit tolerance."
    if error:
        metrics["quality_warning"] = error


def _persistent_quality(context):
    report = context.topology.validation
    if report is None:
        return {}
    return dict(boundary_match=report.boundary_match, guide_preserved=report.guide_preserved)


def _quality_report(report, metrics):
    passed = all(metrics[key] for key in ("no_inversions", "symmetry_ok", "surface_fit_ok"))
    return replace(report, valid=report.valid and passed,
                   symmetry_ok=metrics["symmetry_ok"], fidelity_ok=metrics["surface_fit_ok"],
                   message=metrics.get("quality_warning", report.message))

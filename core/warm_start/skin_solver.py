import time

import numpy as np

from .arap import constrained_arap
from .binding_validation import valid_skin_binding
from .model import SkinWarmResult, WarmInvalidationReason, WarmUpdateStatus, WarmValidationReport
from .signatures import source_connectivity_signature, source_identity_signature


def solve_warm_skin(capture, progress=None):
    started, reason = time.perf_counter(), _compatibility(capture)
    if reason != WarmInvalidationReason.NONE:
        return _fallback(capture, reason, "Warm-start source contracts changed.")
    _report(progress, "Predicting", 0.2)
    predicted = predict_skin_vertices(capture.binding, capture.new_sources)
    corrected = restore_offsets(predicted, capture.binding, capture.new_sources)
    _report(progress, "Relaxing", 0.55)
    relaxed = constrained_arap(capture.vertices, capture.triangles, corrected,
                               capture.structural_signature)
    corrected = collision_containment_correction(relaxed, capture.binding, capture.new_sources)
    corrected = inversion_safe_vertices(capture.vertices, corrected, capture.triangles)
    validation = validate_warm_skin(capture.vertices, capture.triangles, corrected, capture.binding)
    return _result(capture, corrected, validation, started, len(capture.new_sources))


def inversion_safe_vertices(reference, proposal, triangles, steps=10):
    reference, proposal = np.asarray(reference), np.asarray(proposal)
    if _no_inversions(reference, proposal, triangles):
        return proposal
    factor = 0.5
    for _index in range(int(steps)):
        candidate = reference + factor * (proposal - reference)
        if _no_inversions(reference, candidate, triangles):
            return candidate
        factor *= 0.5
    return reference.copy()


def predict_skin_vertices(binding, sources):
    source_map = {int(item.source_index): item for item in sources}
    points = np.zeros((len(binding.weights), 3), dtype=np.float64)
    for influence in range(binding.weights.shape[1]):
        points += _influence_points(binding, source_map, influence)
    return points


def source_triangle_transformations(old_sources, new_sources):
    current = {int(item.source_index): item for item in new_sources}
    values = {}
    for old in old_sources:
        new = current.get(int(old.source_index))
        if new is not None:
            values[int(old.source_index)] = _source_transforms(old, new)
    return values


def _source_transforms(old, new):
    old_triangles = np.asarray(old.vertices)[np.asarray(old.triangles)]
    new_triangles = np.asarray(new.vertices)[np.asarray(new.triangles)]
    old_frames, new_frames = _triangle_frames(old_triangles), _triangle_frames(new_triangles)
    rotations = new_frames @ np.linalg.pinv(old_frames)
    translations = new_triangles[:, 0] - np.einsum("nij,nj->ni", rotations, old_triangles[:, 0])
    return rotations, translations


def _triangle_frames(triangles):
    first = triangles[:, 1] - triangles[:, 0]
    second = triangles[:, 2] - triangles[:, 0]
    normals = np.cross(first, second)
    return np.stack((first, second, normals), axis=2)


def restore_offsets(predicted, binding, sources):
    normals = blended_binding_normals(binding, sources)
    return np.asarray(predicted) + normals * np.asarray(binding.normal_offsets)[:, None]


def blended_binding_normals(binding, sources):
    source_map = {int(item.source_index): item for item in sources}
    normals = np.zeros((len(binding.weights), 3), dtype=np.float64)
    for influence in range(binding.weights.shape[1]):
        normals += _influence_normals(binding, source_map, influence)
    return normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)


def collision_containment_correction(vertices, binding, sources):
    base = predict_skin_vertices(binding, sources)
    normals = blended_binding_normals(binding, sources)
    delta = np.asarray(vertices) - base
    tangent = delta - normals * np.sum(delta * normals, axis=1, keepdims=True)
    return base + tangent + normals * np.asarray(binding.normal_offsets)[:, None]


def validate_warm_skin(reference, triangles, vertices, binding):
    finite = bool(np.isfinite(vertices).all())
    no_inversions = _no_inversions(reference, vertices, triangles)
    coverage = float(np.mean(np.asarray(binding.weights).sum(axis=1) > 0.0))
    displacement = np.linalg.norm(np.asarray(vertices) - reference, axis=1)
    containment = bool(np.isfinite(binding.normal_offsets).all())
    valid = finite and no_inversions and containment and coverage >= 0.95
    message = "Warm skin valid." if valid else "Warm skin failed finiteness, inversion, or coverage validation."
    return WarmValidationReport(valid, finite, no_inversions, containment, coverage,
                                float(np.quantile(displacement, 0.95)), message)


def _compatibility(capture):
    if not valid_skin_binding(capture.binding, capture.new_sources, len(capture.vertices)):
        return WarmInvalidationReason.BINDING_QUALITY
    if capture.binding.schema != 1:
        return WarmInvalidationReason.SCHEMA_MISMATCH
    if capture.expected_structural_signature not in {"", capture.structural_signature}:
        return WarmInvalidationReason.STRUCTURE_CHANGED
    if capture.expected_solver_settings_hash not in {"", capture.solver_settings_hash}:
        return WarmInvalidationReason.SOLVER_SETTINGS_CHANGED
    expected_identity = capture.expected_source_identity_signature or source_identity_signature(capture.old_sources)
    expected_connectivity = (capture.expected_source_connectivity_signature
                             or source_connectivity_signature(capture.old_sources))
    if expected_identity != source_identity_signature(capture.new_sources):
        return WarmInvalidationReason.SOURCE_IDENTITY_CHANGED
    if expected_connectivity != source_connectivity_signature(capture.new_sources):
        return WarmInvalidationReason.SOURCE_CONNECTIVITY_CHANGED
    return WarmInvalidationReason.NONE


def _influence_points(binding, sources, influence):
    output = np.zeros((len(binding.weights), 3), dtype=np.float64)
    for source_index, source in sources.items():
        mask = (binding.source_indices[:, influence] == source_index) & (binding.weights[:, influence] > 0)
        if np.any(mask):
            faces = source.triangles[binding.triangle_indices[mask, influence]]
            output[mask] = np.einsum("ni,nij->nj", binding.barycentric[mask, influence], source.vertices[faces])
    return output * binding.weights[:, influence, None]


def _influence_normals(binding, sources, influence):
    output = np.zeros((len(binding.weights), 3), dtype=np.float64)
    for source_index, source in sources.items():
        mask = (binding.source_indices[:, influence] == source_index) & (binding.weights[:, influence] > 0)
        if np.any(mask):
            faces = source.triangles[binding.triangle_indices[mask, influence]]
            output[mask] = _normals(source.vertices[faces])
    return output * binding.weights[:, influence, None]


def _normals(triangles):
    values = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    return values / np.maximum(np.linalg.norm(values, axis=1, keepdims=True), 1e-12)


def _no_inversions(reference, deformed, triangles):
    old = _normals(np.asarray(reference)[triangles])
    new = _normals(np.asarray(deformed)[triangles])
    return bool(np.all(np.einsum("ij,ij->i", old, new) > 0.0))


def _fallback(capture, reason, message):
    status = WarmUpdateStatus(False, "Fallback", 1.0, message, reason)
    return SkinWarmResult(capture.vertices, capture.binding, status)


def _result(capture, vertices, validation, started, transform_count=0):
    usable = validation.finite and validation.containment
    reason = WarmInvalidationReason.NONE if usable else WarmInvalidationReason.VALIDATION_FAILED
    status = WarmUpdateStatus(usable, "Complete", 1.0, validation.message, reason)
    stats = {"elapsed_seconds": time.perf_counter() - started,
             "geometry_state_hash": capture.geometry_state_hash,
             "transformed_sources": int(transform_count)}
    return SkinWarmResult(vertices, capture.binding, status, validation, stats)


def _report(callback, stage, progress):
    if callback:
        callback(WarmUpdateStatus(True, stage, progress))

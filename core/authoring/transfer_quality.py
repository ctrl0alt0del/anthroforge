"""Sampled diagnostics, explicitly separate from anatomical or collision acceptance."""
import numpy as np
from .transfer_field import evaluate, jacobians


def select_rows(rows, limit):
    return rows[np.linspace(0, len(rows)-1, min(limit, len(rows)), dtype=int)]


def sample_mesh(vertices, triangles, limit):
    vertices, triangles = np.asarray(vertices, dtype=float), np.asarray(triangles, dtype=int)
    corners = select_rows(vertices, max(1, limit//2))
    faces = select_rows(triangles, max(1, limit-len(corners)))
    return np.vstack((corners, vertices[faces].mean(axis=1)))


def landmark_orientation(field, allow_reflection):
    """Use skeletal correspondence, since the RBF polynomial tail omits nonlinear motion."""
    if not allow_reflection:
        return 1
    source = field.centers*field.source_scale+field.source_origin
    target = (evaluate(field, source)-field.target_origin)/field.target_scale
    polynomial = np.column_stack((np.ones(len(source)), field.centers))
    affine = np.linalg.lstsq(polynomial, target, rcond=None)[0][1:]
    return -1 if np.linalg.det(affine) < 0 else 1


def field_report(field, samples, allow_reflection=False):
    values = jacobians(field, samples)
    determinants, stretches = np.linalg.det(values), np.linalg.svd(values, compute_uv=False)
    orientation = landmark_orientation(field, allow_reflection)
    normalized = determinants*orientation/(field.target_scale/field.source_scale)**3
    ratios = stretches[:, 0]/np.maximum(stretches[:, -1], 1e-15)
    low, high = field.centers.min(axis=0), field.centers.max(axis=0)
    coordinates = (samples-field.source_origin)/field.source_scale
    outside = np.any((coordinates < low) | (coordinates > high), axis=1)
    return dict(samples=len(samples), orientation=orientation, min_normalized_jacobian=float(normalized.min()),
                foldover_samples=int(np.count_nonzero(normalized <= 1e-8)), max_axis_ratio=float(ratios.max()),
                min_stretch=float(stretches.min()), max_stretch=float(stretches.max()),
                outside_landmark_aabb_fraction=float(outside.mean()))


def areas(vertices, triangles):
    rows = vertices[triangles]
    return np.linalg.norm(np.cross(rows[:, 1]-rows[:, 0], rows[:, 2]-rows[:, 0]), axis=1)*.5


def mesh_report(field, source, output, triangles, settings):
    samples = sample_mesh(source, triangles, settings.get('samples_per_mesh', 2048))
    report = field_report(field, samples, settings.get('allow_reflection', False))
    old, new = areas(source, triangles), areas(output, triangles)
    usable = old > max(float(old.max()), 1e-20)*1e-12
    ratios = new[usable]/old[usable]/(field.target_scale/field.source_scale)**2
    report['collapsed_triangles'] = int(np.count_nonzero(ratios <= 1e-8))
    report['source_degenerate_triangles'] = int(np.count_nonzero(~usable))
    report['source_usable_triangles'] = int(np.count_nonzero(usable))
    return report


def diagnostic(code, message, severity='warning', related=()):
    return dict(code=code, severity=severity, message=message, document_pointer='', related_ids=list(related))


def diagnostics(reports, landmark_error, settings):
    result = [diagnostic('TRANSFER_REQUIRES_REVIEW', 'Adapted reference meshes; anatomy and collision clearance require separate review.')]
    if landmark_error > settings['max_landmark_error']:
        result.append(diagnostic('TRANSFER_LANDMARK_ERROR', 'Landmark fit exceeds the requested tolerance.', 'error'))
    for name, report in reports.items():
        result.extend(mesh_diagnostics(name, report, settings))
    return result


def mesh_diagnostics(name, report, settings):
    result = []
    if report.get('source_degenerate_triangles', 0):
        severity = 'warning' if report['source_usable_triangles'] else 'error'
        result.append(diagnostic('TRANSFER_SOURCE_DEGENERATE', 'Source contains degenerate triangles.', severity, [name]))
    if report['foldover_samples'] or report.get('collapsed_triangles', 0):
        result.append(diagnostic('TRANSFER_FOLDOVER', 'Sampled folding or collapse; this candidate is unresolved.', 'error', [name]))
    if report['max_axis_ratio'] > settings.get('max_axis_ratio', 10.):
        result.append(diagnostic('TRANSFER_HIGH_DISTORTION', 'Sampled local stretch is strongly anisotropic.', related=[name]))
    if report['outside_landmark_aabb_fraction'] > 0:
        result.append(diagnostic('TRANSFER_EXTRAPOLATION', 'Some samples lie outside landmark axis-aligned bounds.', related=[name]))
    return result


def landmark_report(field, source, target, labels):
    errors = np.linalg.norm(evaluate(field, source)-target, axis=1)
    return dict(max_error=float(errors.max()), rms_error=float(np.sqrt(np.mean(errors**2))),
                points=[dict(id=name, error=float(error)) for name, error in zip(labels, errors)])

"""Independent final-surface checks; a clearance penalty is not certification."""
import numpy as np
from .collision_geometry import report
from ...core.authoring.transfer_quality import diagnostic


def review(target, output, faces, fixed, bones, spec):
    rows = []; tolerance = spec['tolerance']; count = int(spec.get('validation_samples', 512))
    for bone in bones:
        before = report(target, faces, bone, tolerance, count); after = report(output, faces, bone, tolerance, count)
        distance, _nearest, _ambiguous, _fallback = bone.verified(output)
        locked = fixed.astype(bool); inside = distance < -tolerance
        rows.append(dict(obstacle=bone.identity, before=before, after=after,
                         fixed_inside_vertices=int(sum(inside & locked)), movable_inside_vertices=int(sum(inside & ~locked)),
                         fixed_max_penetration=float(max(0, -distance[locked].min(initial=0))),
                         movable_max_penetration=float(max(0, -distance[~locked].min(initial=0))),
                         worsened=after['max_penetration'] > before['max_penetration']+tolerance))
    return dict(collisions=rows, clearance_certificate=False, tolerance=tolerance,
                protected_max_displacement=float(np.linalg.norm(output[fixed.astype(bool)]-target[fixed.astype(bool)], axis=1).max(initial=0)))


def collision_failed(row, tolerance):
    after = row['after']
    return after['max_penetration'] > tolerance or after['reverse_containment']['max_depth'] > tolerance or after['ambiguous_samples'] > 0


def finish(result):
    data = result['shape_preservation']; initial = result['diagnostics']; result['initial_field_diagnostics'] = initial
    result['diagnostics'] = [d for d in initial if d['code'] in ('TRANSFER_REQUIRES_REVIEW', 'TRANSFER_LANDMARK_ERROR', 'TRANSFER_SOURCE_DEGENERATE')]
    collisions = any(collision_failed(r, data['tolerance']) for r in data['collisions'])
    append_diagnostics(result, collisions)
    result['method'] = 'shared_cubic_rbf_shape_clearance.v1'
    result['field_role'] = 'initial_skeletal_guide_only'; result['annotation_mapping'] = 'initial_skeletal_field_not_final_muscle_surface'
    result['validation'].update(collisions='unresolved' if collisions else 'sampled_clear', deformation='final_surface_review_required')
    result['status'] = 'unresolved' if any(d['severity'] == 'error' for d in result['diagnostics']) else 'success'
    return result


def append_diagnostics(result, collisions):
    data = result['shape_preservation']; rows = result['diagnostics']
    if collisions:
        rows.append(diagnostic('TRANSFER_SHAPE_COLLISIONS', 'Residual collisions remain. Inspect fixed bands and movable-region reports.', 'error'))
    if any(r['worsened'] for r in data['collisions']):
        rows.append(diagnostic('TRANSFER_SHAPE_COLLISION_REGRESSION', 'An obstacle has increased sampled penetration; review this candidate.', 'error'))
    if any(r['quality']['collapsed_triangles'] for r in result['meshes']):
        rows.append(diagnostic('TRANSFER_SHAPE_COLLAPSE', 'Final shape contains collapsed triangles.', 'error'))
    if data['fitting']['stop_reason'] == 'iteration_limit':
        rows.append(diagnostic('TRANSFER_SHAPE_ITERATION_LIMIT', 'Fitting reached its bounded iteration budget; convergence is not claimed.'))

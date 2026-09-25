"""Final geometric acceptance after fitting and optional topology-changing cleanup."""
import numpy as np
from .collision_geometry import quality, volume, tree, report, precise_distance


def protected_points(vertices, faces, fixed, contacts):
    mask = np.isin(faces, fixed).all(axis=1)
    contact = np.asarray([c['target'] for c in contacts]).reshape(-1, 3)
    return np.vstack((vertices[fixed], vertices[faces[mask]].mean(axis=1), contact))


def preservation(original, candidate, original_faces, faces, fixed, contacts, settings):
    points = protected_points(original, original_faces, fixed, contacts); bvh = tree(candidate, faces); source = tree(original, original_faces)
    distances = [precise_distance(bvh, candidate, faces, p, settings['tolerance']) for p in points]
    before, after = volume(original, original_faces), volume(candidate, faces)
    return dict(protected_sample_count=len(points), protected_max_distance=float(max(distances, default=0.)),
                signed_volume_before=before, signed_volume_after=after,
                relative_signed_volume_change=abs(after-before)/max(abs(before), 1e-20),
                max_surface_displacement=float(max((bvh.find_nearest(tuple(p))[3] for p in original), default=0.)),
                max_candidate_to_source=float(max((source.find_nearest(tuple(p))[3] for p in candidate), default=0.)))


def collision_failure(report, before, settings):
    if report['ambiguous_samples']:
        return True
    if report['obstacle'] in settings.get('guard_instance_ids', []):
        return report['max_penetration'] > before['max_penetration']+settings['tolerance'] or report['centroid_inside_area'] > before['centroid_inside_area']+settings['tolerance']**2 or report['reverse_containment']['max_depth'] > before['reverse_containment']['max_depth']+settings['tolerance']
    return bool(report['inside_vertices']+report['inside_face_centroids']+report['inside_holdout']+report['reverse_containment']['contained_samples'])


def accept(original, vertices, source_faces, faces, fixed, contacts, obstacles, settings, before):
    keep = preservation(original, vertices, source_faces, faces, fixed, contacts, settings); mesh = quality(vertices, faces, settings['tolerance'])
    collisions = [report(vertices, faces, o, settings['tolerance'], settings.get('validation_samples', 4096)) for o in obstacles]
    reasons = []
    if not mesh['ready']: reasons.append('CORRECTION_MESH_UNRESOLVED')
    if any(collision_failure(r, b, settings) for r, b in zip(collisions, before)): reasons.append('CORRECTION_COLLISION_UNRESOLVED')
    if keep['protected_max_distance'] > settings['tolerance']: reasons.append('CORRECTION_PROTECTION_LOST')
    if keep['relative_signed_volume_change'] > settings.get('max_volume_change', .15): reasons.append('CORRECTION_VOLUME_CHANGE')
    if max(keep['max_surface_displacement'], keep['max_candidate_to_source']) > settings['max_displacement']+settings['tolerance']: reasons.append('CORRECTION_DISPLACEMENT_LIMIT')
    return dict(ready=not reasons, reasons=reasons, mesh=mesh, preservation=keep, collisions=collisions,
                anatomical_review='required', clearance_certificate=False, native_geometry='unchanged')

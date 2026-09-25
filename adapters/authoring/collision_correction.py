"""Collision reports and guarded, local corrections of transferred reference volumes."""
import numpy as np
from ...core.authoring.errors import require
from ...core.authoring.transfer_meshes import world
from ...core.authoring.correction_fit import fit
from .collision_geometry import Obstacle, quality, report
from .collision_cleanup import clean
from .collision_checks import accept
from .collision_reverse import ReverseContacts


def arrays(geometry):
    vertices = world(geometry); faces = np.asarray(geometry['triangles'], int)
    require(0 < len(vertices) <= 30000 and 0 < len(faces) <= 60000, 'COLLISION_MESH_BUDGET')
    require(np.isfinite(vertices).all() and faces.min() >= 0 and faces.max() < len(vertices), 'COLLISION_MESH_INVALID')
    if np.linalg.det(np.asarray(geometry['matrix'])[:3, :3]) < 0:
        faces = faces[:, ::-1]
    return vertices, faces


def obstacles(scene, geometries, tolerance):
    result, checks = [], {}
    for identity, geometry in geometries.items():
        vertices, faces = arrays(geometry); before = quality(vertices, faces)
        require(not before['boundary_edges'], 'COLLISION_OPEN_OBSTACLE', identity)
        if not before['ready']:
            vertices, faces = clean(scene, vertices, faces, epsilon=tolerance*.01)
            if not quality(vertices, faces, tolerance)['ready']:
                vertices, faces = clean(scene, vertices, faces, epsilon=tolerance*.01)
        after = quality(vertices, faces, tolerance); require(after['ready'], 'COLLISION_OBSTACLE_UNRESOLVED', str(dict(instance=identity, quality=after)))
        result.append(Obstacle(identity, vertices, faces, tolerance)); checks[identity] = dict(before=before, evaluated=after, detached_union=not before['ready'])
    return result, checks


def inspect(scene, source, supports, settings):
    vertices, faces = arrays(source['geometry']); bones, checks = obstacles(scene, supports, settings['tolerance'])
    return dict(version='transfer_collisions.v1', units='world_scene_units', source_quality=quality(vertices, faces), obstacle_quality=checks,
                collisions=[report(vertices, faces, o, settings['tolerance'], settings.get('validation_samples', 4096)) for o in bones],
                clearance_certificate=False, anatomical_review='not_evaluated')


def finish_mesh(scene, moved, faces, targets, settings, fitting, before):
    enclosed = any(r['reverse_containment']['contained_samples'] for r in before if r['obstacle'] not in settings.get('guard_instance_ids', []))
    if settings.get('cleanup', 'exact') == 'none' or (fitting.get('stop_reason') == 'already_clear' and not enclosed):
        return moved, faces
    return clean(scene, moved, faces, targets, settings['tolerance']*.01)


def correct(scene, source, supports, settings, fixed, contacts):
    vertices, faces = arrays(source['geometry']); bones, checks = obstacles(scene, supports, settings['tolerance'])
    require(quality(vertices, faces)['ready'], 'CORRECTION_SOURCE_UNRESOLVED', 'Use anatomy.repair_volume before correction.')
    before = [report(vertices, faces, o, settings['tolerance'], settings.get('validation_samples', 4096)) for o in bones]
    moved, fitting, field = fit(vertices, faces, bones, settings, fixed, contacts, ReverseContacts(vertices, faces, bones, settings))
    targets = [o for o in bones if o.identity not in settings.get('guard_instance_ids', [])]
    output, output_faces = finish_mesh(scene, moved, faces, targets, settings, fitting, before)
    validation = accept(vertices, output, faces, output_faces, fixed, contacts, bones, settings, before)
    if fitting.get('max_displacement', 0) > settings['max_displacement']+settings['tolerance']:
        validation['ready'] = False; validation['reasons'].append('CORRECTION_DISPLACEMENT_LIMIT')
    return dict(vertices=output.tolist(), triangles=output_faces.tolist(), field=field, fitting=fitting, validation=validation,
                before=before, obstacle_quality=checks, cleanup=settings.get('cleanup', 'exact'),
                pre_cleanup_quality=quality(moved, faces), source_object='Corrected reference', color=source['color'], quality=validation)

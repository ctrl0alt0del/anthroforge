"""Continuous bone footprint, solid transition and full-surface acceptance checks."""
import numpy as np
from ...core.authoring.errors import require
from ...core.authoring.attachment_footprint import patch, retained, settings_valid
from ...core.authoring.attachment_graft_native import guides
from .attachment_solid import hull, cap_cut, union, repaired
from .attachment_coverage import coverage
from .collision_correction import arrays, obstacles
from .collision_cleanup import clean
from .collision_geometry import quality, report, Obstacle, volume


def build(scene, source, target, settings, fields, patches):
    vertices, faces = arrays(source['geometry']); footprint = patch(target, patches)
    body = retained(vertices, faces, fields, settings['cut_value']); inner = retained(vertices, faces, fields, settings['overlap_cut_value'])
    samples, correspondence = guides(footprint, body, settings); points = footprint[0]
    direction = np.asarray(settings['departure_direction'], float); direction /= np.linalg.norm(direction)
    margin = settings['tolerance']*1.5
    envelope = hull(np.vstack([points-direction*margin, points+direction*margin*4/3, inner[0][inner[2]], samples]))
    return union(scene, cap_cut(body), envelope), footprint, correspondence


def validate(vertices, faces, footprint, bones, settings):
    tolerance = settings['tolerance']; q = quality(vertices, faces, tolerance); diagnostics = []
    rows = [report(vertices, faces, bone, tolerance, settings.get('validation_samples', 4096)) for bone in bones]
    measured = coverage(vertices, faces, *footprint[:2], max(1e-5, tolerance*.002))
    samples = np.vstack([footprint[0], footprint[0][footprint[1]].mean(1)])
    distance = abs(Obstacle('attachment result', vertices, faces, 1e-5).verified(samples)[0]); measured['max_sample_distance'] = float(distance.max())
    if not q['ready'] or q['connected_components'] != 1:
        diagnostics.append('ATTACHMENT_OUTPUT_TOPOLOGY')
    if any(r['max_penetration'] > tolerance or r['reverse_containment']['contained_samples'] for r in rows):
        diagnostics.append('ATTACHMENT_OUTPUT_COLLISION')
    if measured['covered_fraction'] < .9999 or distance.max() > max(1e-4, tolerance*.01):
        diagnostics.append('ATTACHMENT_FOOTPRINT_INCOMPLETE')
    return dict(ready=not diagnostics, reasons=diagnostics, quality=q, collisions=rows, footprint=measured, volume=volume(vertices, faces), anatomical_review='user_review_required')


def preview(scene, source, supports, params):
    settings = params['settings']; settings_valid(settings); owner = params['attachment_instance_id']
    require(owner in supports, 'ATTACHMENT_OWNER_NOT_OBSTACLE')
    bones, checks = obstacles(scene, supports, settings['tolerance'])
    raw, footprint, correspondence = build(scene, source, supports[owner], settings, params['source_cut_values'], params['footprint'])
    moved, faces = clean(scene, *raw, bones, epsilon=1e-7); moved, faces = repaired(moved, faces)
    validation = validate(moved, faces, footprint, bones, settings)
    return dict(vertices=moved.tolist(), triangles=faces.tolist(), color=source['color'], source_object=source['name'] if 'name' in source else 'Attached reference',
                field=None, validation=validation, obstacle_quality=checks, correspondence=correspondence,
                attachment=dict(owner=owner, footprint=params['footprint'], rebuild_on_scp_change=True), quality=validation)

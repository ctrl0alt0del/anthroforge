"""Apply qualified hard targets and report their actual post-fit residuals."""
import numpy as np
from ...core.authoring.transfer_quality import areas


def target_quality(mesh, band):
    ids = np.asarray(band['vertex_indices'], int); faces = np.asarray(mesh['triangles'], int)
    selected = np.flatnonzero(np.isin(faces, ids).all(axis=1)); before = np.asarray(mesh['vertices'])
    after = before.copy(); after[ids] = band['targets']; faces = faces[selected]
    old = areas(before, faces); new = areas(after, faces)
    usable = old > max(float(old.max(initial=0)), 1e-20)*1e-12
    collapsed = selected[usable & (new <= old*1e-8)]
    return dict(fully_constrained_triangles=len(selected), target_collapsed_triangle_indices=collapsed.tolist())


def apply(target, starts, meshes, spec):
    offsets = {row['source_object']: start for row, start in zip(meshes, starts)}
    by_name = {row['source_object']: row for row in meshes}
    reports = []
    for band in spec.get('_attachment_targets', []):
        ids = np.asarray(band['vertex_indices'], int)+offsets[band['source_object']]
        points = np.asarray(band['targets']); distance = np.linalg.norm(target[ids]-points, axis=1)
        target[ids] = points
        reports.append(dict(band, indices=ids, max_initial_target_error=float(distance.max()),
                            mean_initial_target_error=float(distance.mean()), vertex_count=len(ids),
                            **target_quality(by_name[band['source_object']], band)))
    return reports


def review(reports, output):
    result = []
    for row in reports:
        values = dict(row); ids = values.pop('indices')
        errors = np.linalg.norm(output[ids]-np.asarray(row['targets']), axis=1)
        values.update(max_final_target_error=float(errors.max()), constrained_fraction=1.,
                      anatomical_coverage='caller_selected_band_only', surface_area_coverage='not_certified')
        result.append(values)
    return result

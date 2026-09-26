"""Joint reference-family refinement, detached obstacles, and explicit review data."""
import numpy as np
from ...core.authoring.errors import require
from ...core.authoring.transfer_meshes import world
from ...core.authoring.shape_transfer_native import fit
from ...core.authoring.transfer_quality import areas
from .collision_correction import obstacles
from .shape_transfer_review import review, finish
from . import transfer_bands


def pack(sources, meshes, masks):
    names = [row['source_object'] for row in meshes]
    starts = np.cumsum([0]+[len(sources[name]['geometry']['vertices']) for name in names])
    source = np.concatenate([world(sources[name]['geometry']) for name in names])
    target = np.concatenate([np.asarray(row['vertices']) for row in meshes])
    faces = np.concatenate([np.asarray(row['triangles'], int)+start for row, start in zip(meshes, starts)])
    fixed = np.concatenate([masks[name] for name in names])
    return source, target, faces, fixed, starts


def refine(scene, sources, result, supports, masks, spec):
    if 'constraints' in spec:
        from .transfer_constraints import refine as constrained
        return constrained(scene, sources, result, supports, masks, spec)
    return refine_legacy(scene, sources, result, supports, masks, spec)


def refine_legacy(scene, sources, result, supports, masks, spec):
    source, target, faces, fixed, starts = pack(sources, result['meshes'], masks); initial = target.copy()
    orientations = {row['quality']['orientation'] for row in result['meshes']}
    require(len(orientations) == 1, 'TRANSFER_SHAPE_ORIENTATION')
    bones, checks = obstacles(scene, supports, spec['tolerance'])
    bands = transfer_bands.apply(target, starts, result['meshes'], spec)
    candidate = fit(source, target, faces, fixed, bones, spec.get('settings'), orientations.pop())
    audit = review(target, candidate['vertices'], faces, fixed, bones, spec)
    for row, begin, end in zip(result['meshes'], starts[:-1], starts[1:]):
        update_mesh(row, candidate, target, fixed, int(begin), int(end), initial)
    result['shape_preservation'] = dict(family_id=spec['family_id'], fitting=candidate['fitting'], obstacle_quality=checks,
                                      source_order=[r['source_object'] for r in result['meshes']], vertex_offsets=starts.tolist(), **audit)
    result['shape_preservation']['attachment_bands'] = transfer_bands.review(bands, candidate['vertices'])
    return finish(result)


def update_mesh(row, candidate, target, fixed, begin, end, initial):
    output = candidate['vertices'][begin:end]; rest = candidate['rest'][begin:end]; faces = np.asarray(row['triangles'], int)
    row['initial_field_quality'] = row['quality']; old_area = areas(rest, faces); new_area = areas(output, faces)
    usable = old_area > max(float(old_area.max()), 1e-20)*1e-12
    row['quality'] = dict(method='evaluated_shape_matching_surface', collapsed_triangles=int(sum(new_area[usable]/old_area[usable] <= 1e-8)),
                          mean_abs_log_edge_stretch=edge_stretch(rest, output, faces), initial_mean_abs_log_edge_stretch=edge_stretch(rest, initial[begin:end], faces),
                          protected_vertices=int(fixed[begin:end].sum()), fixed_max_displacement=float(np.linalg.norm(output[fixed[begin:end].astype(bool)]-target[begin:end][fixed[begin:end].astype(bool)], axis=1).max(initial=0)),
                          injectivity='not_certified', anatomy='not_evaluated')
    row['vertices'] = output.tolist(); row['attachment_influence'] = candidate['influence'][begin:end].tolist()


def edge_stretch(rest, output, faces):
    edges = np.unique(np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1), axis=0)
    before = np.linalg.norm(rest[edges[:, 0]]-rest[edges[:, 1]], axis=1); after = np.linalg.norm(output[edges[:, 0]]-output[edges[:, 1]], axis=1)
    usable = before > max(before.max(), 1e-20)*1e-12
    return float(np.average(np.abs(np.log(np.maximum(after[usable]/before[usable], 1e-15))), weights=before[usable]))

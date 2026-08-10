import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prototype_topology_instant_meshes as instant


ORIGINAL_TRANSITION = instant.make_transition
COLLAR_SCALE = 1.0


def expanded_guide_mask(vertices, faces, ring):
    center = np.asarray(ring).mean(axis=0)
    radius = np.linalg.norm(np.asarray(ring) - center, axis=1).max()
    scale = 1.0 if abs(float(center[0])) < 0.1 * radius else COLLAR_SCALE
    expanded = center + (scale * (np.asarray(ring) - center))
    return instant.guide_face_mask(vertices, faces, expanded)


def collar_cut_holes(vertices, faces, anchors):
    if not anchors:
        return faces
    masks = [expanded_guide_mask(vertices, faces, instant.global_test.outer_ring(anchor))
             for anchor in anchors]
    return faces[~np.logical_or.reduce(masks)]


def transition_counts(first, second):
    if (first - second) % 2:
        return ()
    step = 2 if second > first else -2
    values = list(range(first, second, step))
    return tuple((*values, second))


def blended_loop(first, second, count, alpha, plane):
    source = instant.cube_test.loop_samples(first, count)
    target = instant.cube_test.loop_samples(second, count)
    smooth = alpha * alpha * (3.0 - (2.0 * alpha))
    points = ((1.0 - smooth) * source) + (smooth * target)
    return enforce_symmetry(points, plane) if plane is not None else points


def enforce_symmetry(points, plane):
    reflected = instant.reflect_points(points, plane)
    distances = np.linalg.norm(points[None, :, :] - reflected[:, None, :], axis=2)
    mapping = np.argmin(distances, axis=1)
    return 0.5 * (points + instant.reflect_points(points[mapping], plane))


def collar_loops(first, second, plane):
    counts = transition_counts(len(first), len(second))
    if not counts:
        return ()
    denominator = max(1, len(counts) - 1)
    return tuple(blended_loop(first, second, count, i / denominator, plane)
                 for i, count in enumerate(counts))


def centered_strip(name, first, second):
    vertices = np.vstack((first, second))
    faces = instant.cube_test.centered_transition_faces(first, second)
    instant.cube_test.validate_transition_boundary(faces, len(first), len(second))
    return instant.cube_test.Transition(name, vertices, faces)


def collar_strip(name, first, second, centered):
    if centered:
        return centered_strip(name, first, second)
    vertices = np.vstack((first, second))
    faces = instant.cube_test.regular_transition_faces(first, second)
    instant.cube_test.validate_transition_boundary(faces, len(first), len(second))
    return instant.cube_test.Transition(name, vertices, faces)


def is_centered(pair, plane, diagonal):
    if plane is None:
        return False
    values = tuple(abs(float(instant.signed_distances(loop.mean(axis=0), plane)))
                   <= 1.0e-5 * diagonal for loop in pair)
    return bool(values[0] and values[1])


def merge_parts(name, parts, diagonal):
    meshes = tuple((item.vertices, item.faces) for item in parts)
    merged = instant.cube_test.welded_hybrid(meshes, 1.0e-7 * diagonal)
    return instant.cube_test.Transition(name, merged.vertices, merged.faces)


def structured_transition(name, pair, diagonal, plane):
    first = instant.cube_test.canonical_loop(pair[0])
    second = instant.cube_test.align_loop(first, pair[1])
    centered = is_centered((first, second), plane, diagonal)
    if centered:
        return ORIGINAL_TRANSITION(name, pair, diagonal, plane)
    if abs(len(first) - len(second)) > 12:
        print(f"AF_COLLAR {name}: incompatible {len(first)} -> {len(second)}, fallback")
        return ORIGINAL_TRANSITION(name, pair, diagonal, plane)
    loops = collar_loops(first, second, plane if centered else None)
    if not loops:
        return ORIGINAL_TRANSITION(name, pair, diagonal, plane)
    print(f"AF_COLLAR {name}: {len(first)} -> {len(second)} via {[len(x) for x in loops]}")
    parts = tuple(collar_strip(name, a, b, centered) for a, b in zip(loops, loops[1:]))
    return merge_parts(name, parts, diagonal)


def install_experiment():
    instant.cut_guide_holes = collar_cut_holes
    instant.make_transition = structured_transition


def main():
    install_experiment()
    instant.main()


if __name__ == "__main__":
    main()

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prototype_topology_instant_meshes as instant


ORIGINAL_TRANSITION = instant.make_transition
OUTER_LEVELS = (0.0, 0.40)
INNER_LEVELS = (0.60, 1.0)


def blend_loop(first, second, count, alpha):
    outer = instant.cube_test.loop_samples(first, count)
    inner = instant.cube_test.loop_samples(second, count)
    smooth = alpha * alpha * (3.0 - (2.0 * alpha))
    return ((1.0 - smooth) * outer) + (smooth * inner)


def patch_loops(first, second):
    outer = (first,) + tuple(blend_loop(first, second, len(first), level) for level in OUTER_LEVELS[1:])
    inner = tuple(blend_loop(first, second, len(second), level) for level in INNER_LEVELS[:-1]) + (second,)
    return outer + inner


def strip_faces(first, second, offset):
    if len(first) == len(second):
        faces = instant.equal_transition_faces(len(first))
    else:
        faces = instant.cube_test.regular_transition_faces(first, second)
    return faces + offset


def assemble_patch(name, loops):
    offsets = np.cumsum((0,) + tuple(len(loop) for loop in loops[:-1]))
    faces = [strip_faces(first, second, offset) for first, second, offset in zip(loops, loops[1:], offsets)]
    vertices = np.vstack(loops)
    return instant.cube_test.Transition(name, vertices, np.vstack(faces))


def patch_score(patch):
    intersections = instant.self_intersection_count(patch.vertices, patch.faces)
    aspects = instant.quad_aspects(patch.vertices, patch.faces)
    return intersections, float(np.quantile(aspects, 0.95))


def best_patch(name, first, second):
    candidates = [assemble_patch(name, patch_loops(first, np.roll(second, shift, axis=0)))
                  for shift in range(-3, 4)]
    scores = [patch_score(item) for item in candidates]
    index = min(range(len(candidates)), key=lambda value: scores[value])
    print(f"AF_RESERVED_SCORE {name}: {scores[index]}", flush=True)
    return candidates[index]


def reserved_transition(name, pair, diagonal, plane):
    boundary, ring = pair
    distance = abs(float(instant.signed_distances(boundary.mean(axis=0), plane)))
    if distance <= 1.0e-5 * diagonal:
        return ORIGINAL_TRANSITION(name, pair, diagonal, plane)
    first = instant.cube_test.canonical_loop(boundary)
    second = instant.cube_test.align_loop(first, ring)
    if abs(len(first) - len(second)) > 14 or (len(first) - len(second)) % 2:
        return ORIGINAL_TRANSITION(name, pair, diagonal, plane)
    print(f"AF_RESERVED_PATCH {name}: {len(first)} -> {len(second)}", flush=True)
    return best_patch(name, first, second)


def transition_distance(item, plane):
    return float(instant.signed_distances(item.vertices.mean(axis=0), plane))


def reflected_transition(source, target, plane):
    vertices = instant.reflect_points(source.vertices, plane)
    return instant.cube_test.Transition(target.name, vertices, source.faces[:, ::-1])


def exact_mirror_pairs(values, diagonal, plane):
    result = list(values)
    negative = [i for i, item in enumerate(values) if transition_distance(item, plane) < -1.0e-5 * diagonal]
    positive = [i for i, item in enumerate(values) if transition_distance(item, plane) > 1.0e-5 * diagonal]
    for source in negative:
        target = min(positive, key=lambda i: np.linalg.norm(values[i].vertices.mean(axis=0) -
                     instant.reflect_points(values[source].vertices.mean(axis=0)[None], plane)[0]))
        result[target] = reflected_transition(values[source], values[target], plane)
    return tuple(result)


def install_experiment():
    instant.make_transition = reserved_transition
    instant.mirror_paired_transitions = exact_mirror_pairs


def main():
    install_experiment()
    instant.main()


if __name__ == "__main__":
    main()

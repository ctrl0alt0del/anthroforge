import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix, diags


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skin", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--variants", required=True)
    return parser.parse_args()


def parse_variants(text):
    result = []
    for item in text.split(","):
        name, window, strength, cap, passes = item.split(":")
        values = float(window), float(strength), float(cap), int(passes)
        result.append((name, *values))
    return result


def triangle_edges(faces):
    edges = np.vstack((faces[:, :2], faces[:, 1:], faces[:, ::2]))
    return np.unique(np.sort(edges, axis=1), axis=0)


def random_walk_adjacency(vertex_count, edges):
    directed = np.vstack((edges, edges[:, ::-1]))
    values = np.ones(len(directed), dtype=np.float64)
    adjacency = coo_matrix((values, (directed[:, 0], directed[:, 1])), shape=(vertex_count,) * 2).tocsr()
    inverse = 1.0 / np.asarray(adjacency.sum(axis=1)).ravel()
    return diags(inverse) @ adjacency


def vertex_normals(vertices, faces):
    triangles = vertices[faces]
    face_normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    normals = np.zeros_like(vertices, dtype=np.float64)
    for corner in range(3):
        np.add.at(normals, faces[:, corner], face_normals)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    return normals / np.maximum(lengths, 1e-12)


def face_normals(vertices, faces):
    triangles = vertices[faces]
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    return normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)


def diffuse(values, adjacency, iterations, blend=0.5):
    result = values.copy()
    for _ in range(iterations):
        result = (1.0 - blend) * result + blend * (adjacency @ result)
    return result


def iteration_count(window, median_edge):
    ratio = window / median_edge
    return min(120, max(2, math.ceil(0.6 * ratio * ratio)))


def safe_normal_move(vertices, faces, normals, lift):
    reference = face_normals(vertices, faces)
    scale = 1.0
    for _ in range(10):
        candidate = vertices + normals * (scale * lift[:, None])
        alignment = np.einsum("ij,ij->i", reference, face_normals(candidate, faces))
        if float(alignment.min()) >= 0.2:
            return candidate, scale * lift, scale
        scale *= 0.5
    return vertices, np.zeros_like(lift), 0.0


def collagen_pass(vertices, faces, adjacency, iterations, strength, cap):
    target = diffuse(vertices, adjacency, iterations)
    normals = vertex_normals(vertices, faces)
    displacement = np.einsum("ij,ij->i", target - vertices, normals)
    raw_lift = strength * np.maximum(displacement, 0.0)
    lift = diffuse(raw_lift, adjacency, max(4, iterations))
    lift = np.clip(lift, 0.0, cap)
    return safe_normal_move(vertices, faces, normals, lift)


def solve_variant(base, faces, adjacency, median_edge, settings):
    name, window, strength, cap, passes = settings
    vertices, lifts, scales = base.copy(), [], []
    iterations = iteration_count(window, median_edge)
    for _ in range(passes):
        vertices, lift, scale = collagen_pass(vertices, faces, adjacency, iterations, strength, cap)
        lifts.append(lift)
        scales.append(scale)
    total_lift = np.sum(lifts, axis=0)
    return name, vertices.astype(np.float32), faces, variant_stats(settings, iterations, total_lift, scales)


def quantiles(values):
    levels = (0.0, 0.5, 0.9, 0.99, 1.0)
    return [float(value) for value in np.quantile(values, levels)]


def variant_stats(settings, iterations, lift, scales):
    name, window, strength, cap, passes = settings
    return {
        "name": name,
        "window": window,
        "strength": strength,
        "cap_per_pass": cap,
        "passes": passes,
        "accepted_scales": scales,
        "diffusion_iterations": iterations,
        "lift_quantiles": quantiles(lift),
    }


def save_result(folder, result):
    name, vertices, faces, stats = result
    np.savez(folder / f"{name}.npz", vertices=vertices, faces=faces)
    with (folder / f"{name}.json").open("w") as handle:
        json.dump(stats, handle, indent=2)


def main(args):
    folder = Path(args.output)
    folder.mkdir(parents=True, exist_ok=True)
    skin = np.load(args.skin)
    vertices, faces = skin["vertices"].astype(np.float64), skin["faces"]
    edges = triangle_edges(faces)
    adjacency = random_walk_adjacency(len(vertices), edges)
    median_edge = float(np.median(np.linalg.norm(vertices[edges[:, 0]] - vertices[edges[:, 1]], axis=1)))
    for settings in parse_variants(args.variants):
        save_result(folder, solve_variant(vertices, faces, adjacency, median_edge, settings))


main(parse_args())

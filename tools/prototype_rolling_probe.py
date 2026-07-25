import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy import ndimage
from scipy.sparse import coo_matrix
from skimage import measure


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--resolution", type=int, default=220)
    parser.add_argument("--variants", required=True)
    return parser.parse_args()


def parse_variants(text):
    result = []
    for item in text.split(","):
        name, probe, offset = item.split(":")
        result.append((name, float(probe), float(offset)))
    return result


def grid_spec(vertices, resolution, margin):
    lower, upper = vertices.min(axis=0), vertices.max(axis=0)
    voxel = float(np.max(upper - lower) / resolution)
    padding = margin + (4.0 * voxel)
    origin = lower - padding
    dimensions = np.ceil((upper - lower + 2.0 * padding) / voxel).astype(int) + 1
    return origin, tuple(dimensions), voxel


def weight_grid(steps, cache):
    if steps in cache:
        return cache[steps]
    indices = np.indices((steps + 1, steps + 1)).reshape(2, -1).T
    indices = indices[indices.sum(axis=1) <= steps]
    uv = indices.astype(np.float64) / steps
    cache[steps] = np.column_stack((1.0 - uv.sum(axis=1), uv))
    return cache[steps]


def triangle_points(triangle, voxel, cache):
    edges = triangle[[1, 2, 0]] - triangle
    steps = max(1, math.ceil(np.linalg.norm(edges, axis=1).max() / (0.45 * voxel)))
    return weight_grid(steps, cache) @ triangle


def rasterize(vertices, faces, origin, dimensions, voxel):
    surface = np.zeros(dimensions, dtype=bool)
    cache = {}
    for index, face in enumerate(faces):
        points = triangle_points(vertices[face], voxel, cache)
        cells = np.rint((points - origin) / voxel).astype(np.int32)
        surface[tuple(cells.T)] = True
        if index and index % 20000 == 0:
            print("raster", index, "/", len(faces), flush=True)
    return ndimage.binary_dilation(surface, iterations=1)


def exterior_centers(surface_distance, stop_distance):
    free = surface_distance > stop_distance
    structure = np.ones((3, 3, 3), dtype=bool)
    labels, count = ndimage.label(free, structure=structure)
    outside = labels == labels[0, 0, 0]
    return outside, count


def prune_body(body):
    labels, _ = ndimage.label(body)
    counts = np.bincount(labels.ravel())
    cutoff = max(64, int(counts[1:].max(initial=0) * 0.001))
    keep = np.flatnonzero(counts >= cutoff)
    keep = keep[keep != 0]
    return np.isin(labels, keep), counts[keep].tolist()


def mesh_body(distance, level, origin, voxel):
    field = distance.astype(np.float32)
    vertices, faces, _, _ = measure.marching_cubes(field, level, spacing=(voxel,) * 3)
    vertices += origin
    return vertices.astype(np.float32), faces.astype(np.int32)


def adjacency_matrix(vertex_count, faces):
    edges = np.vstack((faces[:, :2], faces[:, 1:], faces[:, ::2]))
    edges = np.vstack((edges, edges[:, ::-1]))
    values = np.ones(len(edges), dtype=np.float32)
    return coo_matrix((values, (edges[:, 0], edges[:, 1])), shape=(vertex_count,) * 2).tocsr()


def smooth_pass(vertices, adjacency, factor):
    degree = np.asarray(adjacency.sum(axis=1)).ravel()
    neighbor_mean = adjacency @ vertices / degree[:, None]
    return vertices + factor * (neighbor_mean - vertices)


def taubin_smooth(vertices, faces, iterations=8):
    adjacency = adjacency_matrix(len(vertices), faces)
    result = vertices.astype(np.float64)
    for _ in range(iterations):
        result = smooth_pass(result, adjacency, 0.45)
        result = smooth_pass(result, adjacency, -0.47)
    return result.astype(np.float32)


def orient_outward(vertices, faces):
    triangles = vertices[faces].astype(np.float64)
    crosses = np.cross(triangles[:, 1], triangles[:, 2])
    volume = np.einsum("ij,ij->i", triangles[:, 0], crosses).sum()
    return faces[:, ::-1].copy() if volume < 0.0 else faces


def solve_variant(distance, origin, voxel, probe, offset):
    outside, free_components = exterior_centers(distance, probe + offset)
    reach_distance = ndimage.distance_transform_edt(~outside, sampling=voxel)
    body, body_components = prune_body(reach_distance > probe)
    vertices, faces = mesh_body(reach_distance, probe, origin, voxel)
    vertices = taubin_smooth(vertices, faces)
    faces = orient_outward(vertices, faces)
    return vertices, faces, free_components, body_components


def save_variant(folder, name, vertices, faces, stats):
    np.savez(folder / f"{name}.npz", vertices=vertices, faces=faces)
    with (folder / f"{name}.json").open("w") as handle:
        json.dump(stats, handle, indent=2)


def run(args):
    folder = Path(args.output)
    folder.mkdir(parents=True, exist_ok=True)
    data = np.load(args.input)
    variants = parse_variants(args.variants)
    margin = max(probe + offset for _, probe, offset in variants)
    origin, dimensions, voxel = grid_spec(data["vertices"], args.resolution, margin)
    surface = rasterize(data["vertices"], data["faces"], origin, dimensions, voxel)
    distance = ndimage.distance_transform_edt(~surface, sampling=voxel)
    run_variants(folder, variants, distance, origin, voxel, dimensions)


def run_variants(folder, variants, distance, origin, voxel, dimensions):
    for name, probe, offset in variants:
        print("solve", name, probe, offset, flush=True)
        result = solve_variant(distance, origin, voxel, probe, offset)
        vertices, faces, free_components, body_components = result
        stats = variant_stats(vertices, faces, dimensions, voxel, probe, offset)
        stats.update(free_components=free_components, body_components=body_components)
        save_variant(folder, name, vertices, faces, stats)


def variant_stats(vertices, faces, dimensions, voxel, probe, offset):
    return {
        "vertices": len(vertices),
        "faces": len(faces),
        "grid_dimensions": [int(value) for value in dimensions],
        "voxel": voxel,
        "probe": probe,
        "offset": offset,
    }


if __name__ == "__main__":
    run(parse_args())

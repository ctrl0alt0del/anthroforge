import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix, diags
from scipy.sparse.linalg import LinearOperator, cg
from scipy.spatial import cKDTree


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skin", required=True)
    parser.add_argument("--sources", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--variants", required=True)
    return parser.parse_args()


def parse_variants(text):
    result = []
    for item in text.split(","):
        name, window, falloff, strength, stiffness = item.split(":")
        values = float(window), float(falloff), float(strength), float(stiffness)
        result.append((name, *values))
    return result


def triangle_edges(faces):
    edges = np.vstack((faces[:, :2], faces[:, 1:], faces[:, ::2]))
    return np.unique(np.sort(edges, axis=1), axis=0)


def vertex_normals(vertices, faces):
    triangles = vertices[faces]
    face_normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    normals = np.zeros_like(vertices, dtype=np.float64)
    for corner in range(3):
        np.add.at(normals, faces[:, corner], face_normals)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    return normals / np.maximum(lengths, 1e-12)


def query_scp_anchors(vertices, normals, scp_vertices):
    distances, indices = cKDTree(scp_vertices).query(vertices, k=12, workers=-1)
    candidates = scp_vertices[indices]
    vectors = vertices[:, None, :] - candidates
    directions = vectors / np.maximum(distances[:, :, None], 1e-12)
    alignment = np.einsum("vkj,vj->vk", directions, normals)
    scores = distances + np.where(alignment >= 0.1, 0.0, 1e6)
    choices = np.argmin(scores, axis=1)
    choices[scores[np.arange(len(vertices)), choices] > 1e5] = 0
    return selected_anchors(candidates, distances, choices)


def selected_anchors(candidates, distances, choices):
    rows = np.arange(len(candidates))
    anchors = candidates[rows, choices]
    heights = distances[rows, choices]
    return anchors, heights


def edge_geometry(vertices, faces):
    edges = triangle_edges(faces)
    lengths = np.linalg.norm(vertices[edges[:, 0]] - vertices[edges[:, 1]], axis=1)
    return edges, lengths


def propagate_once(field, edges, costs):
    result = field.copy()
    np.maximum.at(result, edges[:, 0], field[edges[:, 1]] - costs)
    np.maximum.at(result, edges[:, 1], field[edges[:, 0]] - costs)
    return result


def collagen_envelope(heights, edges, lengths, window, falloff):
    steps = max(1, math.ceil(window / np.median(lengths)))
    field = heights.copy()
    for _ in range(steps):
        field = propagate_once(field, edges, falloff * lengths)
    return np.maximum(field, heights), steps


def normalized_adjacency(vertex_count, edges):
    directed = np.vstack((edges, edges[:, ::-1]))
    values = np.ones(len(directed), dtype=np.float64)
    adjacency = coo_matrix((values, (directed[:, 0], directed[:, 1])), shape=(vertex_count,) * 2).tocsr()
    inverse = 1.0 / np.sqrt(np.asarray(adjacency.sum(axis=1)).ravel())
    return diags(inverse) @ adjacency @ diags(inverse)


def plate_operator(adjacency, stiffness):
    def multiply(values):
        laplacian = values - adjacency @ values
        return values + stiffness * (laplacian - adjacency @ laplacian)
    shape = adjacency.shape
    return LinearOperator(shape, matvec=multiply, dtype=np.float64)


def plate_smooth(values, adjacency, stiffness):
    result, info = cg(plate_operator(adjacency, stiffness), values, rtol=1e-5, maxiter=100)
    return np.maximum(result, 0.0), int(info)


def movement_directions(vertices, anchors, normals):
    anchor_vectors = vertices - anchors
    anchor_vectors /= np.maximum(np.linalg.norm(anchor_vectors, axis=1, keepdims=True), 1e-12)
    directions = anchor_vectors + normals
    directions /= np.maximum(np.linalg.norm(directions, axis=1, keepdims=True), 1e-12)
    return directions


def solve_variant(context, settings):
    name, window, falloff, strength, stiffness = settings
    support = context["support_heights"]
    envelope, steps = collagen_envelope(support, context["edges"], context["lengths"], window, falloff)
    raw_lift = strength * np.maximum(envelope - support, 0.0)
    lift, info = plate_smooth(raw_lift, context["adjacency"], stiffness)
    lift = np.minimum(lift, min(0.03, 0.35 * window))
    vertices = context["vertices"] + context["normals"] * lift[:, None]
    stats = variant_stats(settings, context["heights"], lift, steps, info)
    return name, vertices.astype(np.float32), context["faces"], stats


def quantiles(values):
    levels = (0.0, 0.5, 0.9, 0.99, 1.0)
    return [float(value) for value in np.quantile(values, levels)]


def variant_stats(settings, heights, lift, steps, info):
    name, window, falloff, strength, stiffness = settings
    return {
        "name": name,
        "window": window,
        "falloff": falloff,
        "strength": strength,
        "stiffness": stiffness,
        "propagation_steps": steps,
        "height_quantiles": quantiles(heights),
        "lift_quantiles": quantiles(lift),
        "cg_info": info,
    }


def build_context(skin, sources):
    vertices, faces = skin["vertices"].astype(np.float64), skin["faces"]
    normals = vertex_normals(vertices, faces)
    scp_vertices = sources["vertices"][sources["vertex_kinds"] == "SCP"]
    anchors, heights = query_scp_anchors(vertices, normals, scp_vertices)
    edges, lengths = edge_geometry(vertices, faces)
    adjacency = normalized_adjacency(len(vertices), edges)
    support_heights, _ = plate_smooth(heights, adjacency, 100.0)
    return dict(vertices=vertices, faces=faces, heights=heights, support_heights=support_heights, edges=edges, lengths=lengths, adjacency=adjacency, normals=normals)


def save_result(folder, result):
    name, vertices, faces, stats = result
    np.savez(folder / f"{name}.npz", vertices=vertices, faces=faces)
    with (folder / f"{name}.json").open("w") as handle:
        json.dump(stats, handle, indent=2)


def main(args):
    folder = Path(args.output)
    folder.mkdir(parents=True, exist_ok=True)
    skin, sources = np.load(args.skin), np.load(args.sources)
    context = build_context(skin, sources)
    print("height_quantiles", quantiles(context["heights"]), flush=True)
    for settings in parse_variants(args.variants):
        save_result(folder, solve_variant(context, settings))


main(parse_args())

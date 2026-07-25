import argparse
import json
from pathlib import Path

import numpy as np
from scipy import ndimage
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from prototype_rest_envelope import exterior_field, extract_mesh, face_groups
from prototype_rest_envelope import smooth_max, surface_distance
from prototype_rolling_probe import grid_spec

ZERO_TERMS = ("ear", "cartilage", "nasal")
EYE_TERMS = ("eyes",)
MOUTH_TERMS = ("lip", "mouth")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--resolution", type=int, default=220)
    parser.add_argument("--variants", required=True)
    return parser.parse_args()


def parse_variants(text):
    result = []
    for item in text.split(","):
        values = item.split(":")
        if len(values) == 3:
            values.extend(("0.15", "0.15"))
        name, zero_outer, low_outer, eye_min, mouth_min = values
        result.append((name, *map(float, (zero_outer, low_outer, eye_min, mouth_min))))
    return result


def vertex_source_names(data):
    names = np.empty(len(data["vertices"]), dtype="<U64")
    cursor = 0
    for name, _, count in json.loads(str(data["metadata"])):
        names[cursor : cursor + count] = name.lower()
        cursor += count
    return names


def semantic_faces(data, terms):
    names = vertex_source_names(data)
    face_names = names[data["faces"][:, 0]]
    selected = np.zeros(len(face_names), dtype=bool)
    for term in terms:
        selected |= np.char.find(face_names, term) >= 0
    return data["faces"][selected]


def falloff(distance, inner, outer, minimum):
    factor = np.clip((distance - inner) / (outer - inner), 0.0, 1.0)
    factor = factor * factor * (3.0 - 2.0 * factor)
    return minimum + (1.0 - minimum) * factor


def collagen_grid(distances, settings):
    zero_distance, eye_distance, mouth_distance = distances
    _, zero_outer, low_outer, eye_min, mouth_min = settings
    zero = falloff(zero_distance, 0.06, zero_outer, 0.0)
    eyes = falloff(eye_distance, 0.05, low_outer, eye_min)
    mouth = falloff(mouth_distance, 0.05, low_outer, mouth_min)
    return np.minimum(zero, np.minimum(eyes, mouth))


def sample_grid(grid, vertices, origin, voxel):
    coordinates = ((vertices - origin) / voxel).T
    return ndimage.map_coordinates(grid, coordinates, order=1, mode="nearest")


def volume(vertices, faces):
    triangles = vertices[faces].astype(np.float64)
    cross = np.cross(triangles[:, 1], triangles[:, 2])
    return np.einsum("ij,ij->i", triangles[:, 0], cross).sum() / 6.0


def face_edges(faces):
    edges = np.vstack((faces[:, :2], faces[:, 1:], faces[:, ::2]))
    return np.sort(edges, axis=1)


def largest_component(vertices, faces):
    edges = face_edges(faces)
    graph_edges = np.vstack((edges, edges[:, ::-1]))
    graph = coo_matrix((np.ones(len(graph_edges)), graph_edges.T), shape=(len(vertices),) * 2)
    _, labels = connected_components(graph.tocsr(), directed=False)
    selected = faces[labels[faces[:, 0]] == np.bincount(labels[faces[:, 0]]).argmax()]
    used = np.unique(selected)
    remap = np.full(len(vertices), -1, dtype=np.int32)
    remap[used] = np.arange(len(used), dtype=np.int32)
    return vertices[used], remap[selected]


def save_result(folder, settings, field, collagen, origin, voxel):
    vertices, faces = extract_mesh(field, origin, voxel)
    vertices, faces = largest_component(vertices, faces)
    values = sample_grid(collagen, vertices, origin, voxel)
    np.savez(folder / f"{settings[0]}.npz", vertices=vertices, faces=faces, collagen=values)
    stats = result_stats(settings, vertices, faces, values, voxel)
    with (folder / f"{settings[0]}.json").open("w") as handle:
        json.dump(stats, handle, indent=2)


def result_stats(settings, vertices, faces, values, voxel):
    name, zero_outer, low_outer, eye_min, mouth_min = settings
    return dict(name=name, zero_outer=zero_outer, low_outer=low_outer,
                eye_min=eye_min, mouth_min=mouth_min,
                voxel=voxel, vertices=len(vertices), faces=len(faces),
                volume=volume(vertices, faces), collagen_mean=float(values.mean()))


def solve(folder, variants, distances, fields, origin, voxel):
    required, full = fields
    for settings in variants:
        print("variable_collagen", *settings, flush=True)
        collagen = collagen_grid(distances, settings)
        field = required + collagen * (full - required)
        save_result(folder, settings, field, collagen, origin, voxel)


def semantic_distances(data, origin, dimensions, voxel):
    groups = (ZERO_TERMS, EYE_TERMS, MOUTH_TERMS)
    return tuple(surface_distance(data["vertices"], semantic_faces(data, terms),
                                  origin, dimensions, voxel) for terms in groups)


def main(args):
    folder = Path(args.output)
    folder.mkdir(parents=True, exist_ok=True)
    data = np.load(args.sources)
    variants = parse_variants(args.variants)
    margin = max(0.18, max(item[1] for item in variants))
    origin, dimensions, voxel = grid_spec(data["vertices"], args.resolution, margin)
    all_faces, scp_faces = face_groups(data)
    combined = surface_distance(data["vertices"], all_faces, origin, dimensions, voxel)
    rest = surface_distance(data["vertices"], scp_faces, origin, dimensions, voxel)
    distances = semantic_distances(data, origin, dimensions, voxel)
    required = exterior_field(combined, voxel, 0.06, 0.015)
    full = smooth_max(exterior_field(rest, voxel, 0.12, 0.04), required, 0.012)
    solve(folder, variants, distances, (required, full), origin, voxel)


if __name__ == "__main__":
    main(parse_args())

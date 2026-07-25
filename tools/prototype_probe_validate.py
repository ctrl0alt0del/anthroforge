import argparse
import json
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    return parser.parse_args()


def triangle_edges(faces):
    edges = np.vstack((faces[:, :2], faces[:, 1:], faces[:, ::2]))
    return np.sort(edges, axis=1)


def edge_stats(faces):
    _, counts = np.unique(triangle_edges(faces), axis=0, return_counts=True)
    return int(np.count_nonzero(counts == 1)), int(np.count_nonzero(counts > 2))


def component_count(vertex_count, faces):
    edges = triangle_edges(faces)
    edges = np.vstack((edges, edges[:, ::-1]))
    graph = coo_matrix((np.ones(len(edges)), (edges[:, 0], edges[:, 1])), shape=(vertex_count,) * 2)
    return int(connected_components(graph.tocsr(), directed=False, return_labels=False))


def geometry_stats(vertices, faces):
    triangles = vertices[faces].astype(np.float64)
    cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    areas = 0.5 * np.linalg.norm(cross, axis=1)
    volume = np.einsum("ij,ij->i", triangles[:, 0], np.cross(triangles[:, 1], triangles[:, 2])).sum() / 6.0
    return int(np.count_nonzero(areas < 1e-12)), float(volume), float(areas.min())


def validate(path):
    data = np.load(path)
    vertices, faces = data["vertices"], data["faces"]
    boundary, nonmanifold = edge_stats(faces)
    degenerates, volume, minimum_area = geometry_stats(vertices, faces)
    result = validation_record(path, vertices, faces)
    result.update(boundary_edges=boundary, nonmanifold_edges=nonmanifold)
    result.update(degenerate_faces=degenerates, signed_volume=volume)
    result.update(minimum_area=minimum_area, finite=bool(np.isfinite(vertices).all()))
    return result


def validation_record(path, vertices, faces):
    return {
        "file": str(path),
        "vertices": len(vertices),
        "faces": len(faces),
        "components": component_count(len(vertices), faces),
    }


for item in parse_args().paths:
    print(json.dumps(validate(Path(item)), indent=2))

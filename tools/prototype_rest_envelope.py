import argparse
import json
from pathlib import Path

import numpy as np
from scipy import ndimage
from skimage import measure

from prototype_rolling_probe import grid_spec, orient_outward, rasterize, taubin_smooth


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
        name, probe, offset, blend = item.split(":")
        result.append((name, float(probe), float(offset), float(blend)))
    return result


def face_groups(data):
    kinds = data["vertex_kinds"]
    faces = data["faces"]
    return faces, faces[kinds[faces[:, 0]] == "SCP"]


def surface_distance(vertices, faces, origin, dimensions, voxel):
    surface = rasterize(vertices, faces, origin, dimensions, voxel)
    return ndimage.distance_transform_edt(~surface, sampling=voxel)


def exterior_field(distance, voxel, probe, offset):
    free = distance > probe + offset
    labels, _ = ndimage.label(free, structure=np.ones((3, 3, 3), dtype=bool))
    outside = labels == labels[0, 0, 0]
    reach = ndimage.distance_transform_edt(~outside, sampling=voxel)
    return reach - probe


def smooth_max(first, second, radius):
    if radius <= 0.0:
        return np.maximum(first, second)
    weight = np.clip(0.5 + 0.5 * (first - second) / radius, 0.0, 1.0)
    return second * (1.0 - weight) + first * weight + radius * weight * (1.0 - weight)


def extract_mesh(field, origin, voxel):
    vertices, faces, _, _ = measure.marching_cubes(field.astype(np.float32), 0.0, spacing=(voxel,) * 3)
    vertices = taubin_smooth(vertices + origin, faces, iterations=8)
    faces = orient_outward(vertices, faces)
    return vertices, faces


def mesh_stats(vertices, faces, settings, voxel):
    triangles = vertices[faces].astype(np.float64)
    cross = np.cross(triangles[:, 1], triangles[:, 2])
    volume = np.einsum("ij,ij->i", triangles[:, 0], cross).sum() / 6.0
    name, probe, offset, blend = settings
    return dict(name=name, rest_probe=probe, rest_offset=offset, blend=blend, voxel=voxel, vertices=len(vertices), faces=len(faces), volume=volume)


def save_result(folder, settings, field, origin, voxel):
    name = settings[0]
    vertices, faces = extract_mesh(field, origin, voxel)
    np.savez(folder / f"{name}.npz", vertices=vertices, faces=faces)
    with (folder / f"{name}.json").open("w") as handle:
        json.dump(mesh_stats(vertices, faces, settings, voxel), handle, indent=2)


def solve_variants(folder, variants, rest_distance, required, origin, voxel):
    for settings in variants:
        name, probe, offset, blend = settings
        print("rest_envelope", name, probe, offset, blend, flush=True)
        rest = exterior_field(rest_distance, voxel, probe, offset)
        save_result(folder, settings, smooth_max(rest, required, blend), origin, voxel)


def main(args):
    folder = Path(args.output)
    folder.mkdir(parents=True, exist_ok=True)
    data = np.load(args.sources)
    variants = parse_variants(args.variants)
    margin = max(probe + offset for _, probe, offset, _ in variants)
    origin, dimensions, voxel = grid_spec(data["vertices"], args.resolution, margin)
    all_faces, scp_faces = face_groups(data)
    combined_distance = surface_distance(data["vertices"], all_faces, origin, dimensions, voxel)
    rest_distance = surface_distance(data["vertices"], scp_faces, origin, dimensions, voxel)
    required = exterior_field(combined_distance, voxel, 0.06, 0.015)
    solve_variants(folder, variants, rest_distance, required, origin, voxel)


if __name__ == "__main__":
    main(parse_args())

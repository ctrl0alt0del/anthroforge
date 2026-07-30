import argparse
import sys
from pathlib import Path

import numpy as np


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--vendor", required=True)
    parser.add_argument("--target-vertices", type=int, required=True)
    return parser.parse_args()


def remesh(args):
    sys.path.insert(0, args.vendor)
    import pyinstantmeshes
    with np.load(args.input, allow_pickle=False) as values:
        vertices, faces = values["vertices"], values["faces"]
    input_path, output_path = obj_paths(args.output)
    write_obj(input_path, vertices, faces)
    pyinstantmeshes.remesh_file(str(input_path), str(output_path),
                                target_vertex_count=args.target_vertices, rosy=4, posy=4,
                                pure_quad=True, deterministic=True, smooth_iterations=6,
                                align_to_boundaries=True)
    return read_obj(output_path)


def obj_paths(output):
    folder = Path(output).parent
    return folder / "instant_input.obj", folder / "instant_output.obj"


def write_obj(path, vertices, faces):
    with path.open("w", encoding="utf-8") as stream:
        for vertex in vertices:
            stream.write("v " + " ".join(map(str, vertex)) + "\n")
        for face in faces:
            stream.write("f " + " ".join(str(int(value) + 1) for value in face) + "\n")


def read_obj(path):
    vertices, faces = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("v "):
            vertices.append(tuple(map(float, line.split()[1:4])))
        elif line.startswith("f "):
            faces.append(tuple(int(value.split("/")[0]) - 1 for value in line.split()[1:]))
    return np.asarray(vertices, dtype=np.float32), np.asarray(faces, dtype=np.int32)


def main():
    args = parse_args()
    vertices, faces = remesh(args)
    np.savez(args.output, vertices=vertices, faces=faces)


if __name__ == "__main__":
    main()

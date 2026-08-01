import sys
from pathlib import Path

import numpy as np


def remesh_file(input_path, output_path, vendor, count):
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    import pyinstantmeshes
    with np.load(input_path, allow_pickle=False) as data:
        vertices, faces = data["vertices"], data["faces"]
    source = Path(output_path).with_suffix(".input.obj")
    target = Path(output_path).with_suffix(".output.obj")
    _write_obj(source, vertices, faces)
    pyinstantmeshes.remesh_file(
        str(source), str(target), target_vertex_count=int(count), rosy=4, posy=4,
        pure_quad=True, deterministic=True, smooth_iterations=6,
        align_to_boundaries=True)
    vertices, faces = _read_obj(target)
    np.savez(output_path, vertices=np.asarray(vertices), faces=np.asarray(faces))


def _write_obj(path, vertices, faces):
    with path.open("w", encoding="utf-8") as stream:
        for vertex in vertices:
            stream.write("v " + " ".join(map(str, vertex)) + "\n")
        for face in faces:
            stream.write("f " + " ".join(str(int(x) + 1) for x in face) + "\n")


def _read_obj(path):
    vertices, faces = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("v "):
            vertices.append(tuple(map(float, line.split()[1:4])))
        elif line.startswith("f "):
            faces.append(tuple(int(x.split("/")[0]) - 1 for x in line.split()[1:]))
    return np.asarray(vertices), np.asarray(faces)

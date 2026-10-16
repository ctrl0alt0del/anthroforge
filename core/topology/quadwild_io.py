"""Validated file exchange with the bundled native remesher."""
from pathlib import Path
import numpy as np


def write_obj(path, vertices, faces):
    with Path(path).open("w", encoding="utf-8") as stream:
        for p in vertices: stream.write("v " + " ".join(format(float(x), ".17g") for x in p) + "\n")
        for f in faces: stream.write("f " + " ".join(str(int(x)+1) for x in f) + "\n")


def read_obj(path, arity):
    vertices, faces = [], []
    for line in Path(path).read_text().splitlines():
        if line.startswith("v "): vertices.append(list(map(float, line.split()[1:4])))
        if line.startswith("f "): faces.append([int(x.split("/")[0])-1 for x in line.split()[1:]])
    if not faces or any(len(f) != arity for f in faces): raise ValueError("Native remesher produced missing or invalid polygons.")
    v, f = np.asarray(vertices, np.float64), np.asarray(faces, np.int32)
    if v.ndim != 2 or v.shape[1] != 3 or not np.isfinite(v).all(): raise ValueError("Nonfinite native topology.")
    if f.min() < 0 or f.max() >= len(v): raise ValueError("Invalid native vertex identities.")
    return v, f


def read_field(path, count):
    rows = [list(map(float, s.split())) for s in Path(path).read_text().splitlines() if len(s.split()) == 3]
    result = np.asarray(rows)
    if result.shape != (count, 3) or not np.isfinite(result).all(): raise ValueError("Native prior field mismatch.")
    return result


def write_features(path, faces, edges):
    desired = {tuple(sorted(e)) for e in edges}; rows = []
    for i, f in enumerate(faces):
        for j in range(3):
            edge = tuple(sorted((f[j], f[(j+1)%3])))
            if edge in desired: rows.append((1, i, j)); desired.remove(edge)
    np.savetxt(path, np.asarray(rows).reshape(-1, 3), fmt="%d", delimiter=",", header=str(len(rows)), comments="")
    return len(rows)

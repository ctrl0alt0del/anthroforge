"""Normalized anatomical boxes, units and intrinsic region coordinates."""
import numpy as np
from .errors import require
from .geometry import normalized


def targets(document, snapshot):
    result = {}
    for name, target in document["targets"].items():
        binding = target["binding"]
        candidates = [m for m in snapshot.meshes if _matches(m, binding)]
        require(len(candidates) == 1, "TARGET_NOT_FOUND" if not candidates else "TARGET_AMBIGUOUS",
                pointer="/targets/" + name + "/binding")
        result[name] = candidates[0]
    return result


def _matches(mesh, binding):
    if binding["kind"] == "scene_scp_id":
        return mesh.id == binding["id"]
    return mesh.concept == binding["concept"] and mesh.side == binding["side"]


def frame(spec, mesh):
    from .extensions import landmark_basis
    basis = landmark_basis(spec,mesh.vertices) if spec["kind"] == "landmark_box" else np.asarray(spec["axes_owner_local"]).T
    local = mesh.vertices @ basis
    low, high = local.min(axis=0), local.max(axis=0)
    require(bool(np.all(high - low > 1e-12)), "DEGENERATE_FRAME")
    linear = mesh.matrix[:3, :3] @ basis
    require(abs(np.linalg.det(linear)) > 1e-12, "DEGENERATE_FRAME")
    return dict(mesh=mesh, low=low, extent=high - low, linear=linear,
                translation=mesh.matrix[:3, 3], normal=np.linalg.inv(linear).T)


def position(chart, q):
    return chart["linear"] @ (chart["low"] + chart["extent"] * q) + chart["translation"]


def length(spec, document, frames, references=None):
    if "unit" in spec:
        scale = 1 if spec["unit"] == "scene" else .001 / document["context"]["units"]["meters_per_scene_unit"]
        return spec["value"] * scale
    if spec["of"] == "frame_extent":
        chart, axis = frames[spec["frame"]], "xyz".index(spec["axis"])
        scale = np.linalg.norm(chart["linear"][:, axis]) * chart["extent"][axis]
    else:
        require(references is not None and spec["of"] in references, "UNAVAILABLE_REFERENCE_LENGTH")
        scale = references[spec["of"]]
        require(scale > 0, "ZERO_REFERENCE_LENGTH")
    return float(spec["fraction"] * scale)


def seed(definition, at):
    kind = definition["kind"]
    if kind == "point":
        return np.asarray(definition["seed"])
    if kind == "curve":
        return curve_seed(definition, float(at[0]))
    r, t = at
    q00, q10, q11, q01 = np.asarray(definition["corners"])
    return (1-r)*(1-t)*q00 + r*(1-t)*q10 + r*t*q11 + (1-r)*t*q01


def curve_seed(definition, t):
    values = np.asarray(definition["seeds"])
    if definition["closed"]:
        values = np.vstack((values, values[0]))
    x = min(t * (len(values) - 1), len(values) - 1)
    i = min(int(x), len(values) - 2)
    return values[i] * (1 - x + i) + values[i + 1] * (x - i)


def footprint(sample, u):
    kind = sample["kind"]
    if kind == "point":
        return ()
    if kind == "curve_span":
        return (sample["start"] * (1-u) + sample["end"] * u,)
    return tuple(np.asarray(sample["start"]) * (1-u) + np.asarray(sample["end"]) * u)

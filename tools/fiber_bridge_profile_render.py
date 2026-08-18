"""Render the bridge correction in its tangent/normal profile plane."""

import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_pin_smoothing_render as view
import fiber_v25_branch2_render as render


def _unit(value):
    length = float(np.linalg.norm(value))
    return np.asarray(value) / length if length > 1.0e-12 else np.zeros(3)


def _bridge_edges(record):
    rows = tuple(row for row in record["request"]["spans"] if row["branch"] == "SURFACE_BRIDGE")
    first = min(row["first_edge"] for row in rows); last = max(row["first_edge"] + row["edge_count"] for row in rows)
    return first, last


def _profile_axes(record, paths):
    first, last = _bridge_edges(record); baseline, improved = paths[2], paths[3]
    tangent = _unit(baseline[last] - baseline[first])
    lift = np.mean(baseline[first:last + 1] - improved[first:last + 1], axis=0)
    normal = _unit(lift - np.dot(lift, tangent) * tangent)
    side = _unit(np.cross(tangent, normal)); return np.vstack((tangent, normal, side))


def _profile_frame(record, paths):
    axes = _profile_axes(record, paths); cloud = np.vstack(paths); center = cloud.mean(axis=0)
    bounds = (cloud - center) @ axes.T; span = np.maximum(np.ptp(bounds[:, :2], axis=0), 1.0e-4)
    return center, axes, max(span[0] / 1.35, span[1] / 1.05, 1.0e-4)


def main():
    args = render._args(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    render.base._reset_scene(); paths = render._paths(record); frame = _profile_frame(record, paths)
    names = "Stored V1", "Planner", "V2.4", "Bridge-aware recovery"; materials = view._materials()
    for index, (name, path) in enumerate(zip(names, paths)):
        render._tile(record, path, name, index, frame, materials)
    render._finish(output, args.blend_output)


if __name__ == "__main__":
    main()

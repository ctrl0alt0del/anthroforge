"""Real-Blender proximal regularized-SQP ablation with zero curvature."""

import json
from dataclasses import asdict
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_true_length_improvements as fixes
import fiber_v2_true_length_irls as base
from anthroforge.core.vcp.v2.contact_core import V2ContactExperiment


IRLS = dict(true_length_irls=True)
VARIANTS = (
    ("BASE", V2ContactExperiment(**IRLS)),
    ("REG_1E8", V2ContactExperiment(**IRLS, sqp_regularization_ratio=1.0e-8)),
    ("REG_1E6", V2ContactExperiment(**IRLS, sqp_regularization_ratio=1.0e-6)),
    ("REG_1E4", V2ContactExperiment(**IRLS, sqp_regularization_ratio=1.0e-4)),
    ("REG_1E2", V2ContactExperiment(**IRLS, sqp_regularization_ratio=1.0e-2)),
    ("REG_1", V2ContactExperiment(**IRLS, sqp_regularization_ratio=1.0)),
    ("REG_ADAPTIVE", V2ContactExperiment(**IRLS, sqp_regularization_ratio=1.0e-6,
                                          adaptive_regularized_sqp=True)),
    ("REG_ADAPTIVE_SPACING", V2ContactExperiment(**IRLS, adaptive_quality=True,
        sqp_regularization_ratio=1.0e-6, adaptive_regularized_sqp=True)),
)
SELECTED = (VARIANTS[0], VARIANTS[-2], VARIANTS[-1])


def _variant(name, experiment, request, snapshot, seed, pins, repeats):
    return fixes._variant(name, experiment, request, snapshot, seed, pins, repeats)


def _record(args):
    fiber, request, snapshot, capture, planner, pins, seed, shortcut = fixes._prepared(args)
    current = fixes._variant_request(request, seed, 0.0)
    variants = VARIANTS if args.suite == "all" else SELECTED
    rows = {name: _variant(name, experiment, current, snapshot, seed, pins, args.repeats)
            for name, experiment in variants}
    routes = [np.asarray(row["result_points"]) for row in rows.values()]
    return {"experiment": "zero-curvature proximal regularized SQP", "file": base.bpy.data.filepath,
        "file_sha256": fixes.common._file_hash(base.bpy.data.filepath), "fiber": fiber.id,
        "capture_ms": capture, "accepted_cap": args.accepted_cap, "pin_indices": pins,
        "planner": {"mode": planner.mode.value, "branches": [row.branch.value for row in planner.spans]},
        "shortcut": shortcut, "variants": rows, "nearby_triangles": base.p3._nearby(snapshot, routes)}


def _regularization(row):
    spans = row["trace"]["spans"]
    histories = [span["regularization_history"] for span in spans if span["regularization_history"]]
    return {"initial": [values[0] for values in histories], "final": [values[-1] for values in histories]}


def _summary(row):
    result = fixes._summary(row); result["regularization"] = _regularization(row)
    return result


def main():
    args = base._args(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_V2_REGULARIZED_SQP", json.dumps(
        {key: _summary(row) for key, row in record["variants"].items()}), flush=True)


if __name__ == "__main__":
    main()

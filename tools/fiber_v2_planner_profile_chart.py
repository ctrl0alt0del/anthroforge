"""Render the Package 4 production phase-profile comparison."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


_GROUPS = (
    ("Graph search", ("compatibility_search", "roadmap_search"), "#7B61FF"),
    ("Collision Python", ("segment_batch_clearance", "static_clearance"), "#E6654A"),
    ("Native distance", ("native_distance",), "#F2B84B"),
    ("Native containment", ("native_containment",), "#D8498B"),
    ("Native broad phase", ("native_broad_phase",), "#4C9BE8"),
    ("Candidates/surface", ("compatibility_candidates", "roadmap_candidates", "surface_route"), "#49B77D"),
    ("Other", (), "#8793A1"),
)


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", nargs=3, required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def _load(paths):
    return [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]


def _group_value(row, keys):
    phases = row["phases"]
    return sum(phases.get(key, {}).get("exclusive_ms_median", 0.0) for key in keys)


def _values(row):
    assigned = sum(_group_value(row, keys) for _name, keys, _color in _GROUPS[:-1])
    total = row["v2_traced"]["median_ms"]
    return [_group_value(row, keys) if keys else max(0.0, total - assigned)
            for _name, keys, _color in _GROUPS]


def _draw_totals(axis, rows, labels):
    x = np.arange(len(rows)); width = 0.25
    axis.bar(x - width, [row["v1"]["median_ms"] for row in rows], width, label="V1", color="#65717F")
    axis.bar(x, [row["v2"]["median_ms"] for row in rows], width, label="Package 4", color="#E6654A")
    axis.bar(x + width, [row["cached_native_dispatch"]["median_ms"] for row in rows], width,
             label="P4 cached native dispatch", color="#49B77D")
    axis.set_xticks(x, labels); axis.set_ylabel("Planner median (ms)"); axis.legend(frameon=False)


def _draw_phases(axis, rows, labels):
    left = np.zeros(len(rows))
    for index, (name, _keys, color) in enumerate(_GROUPS):
        values = np.asarray([_values(row)[index] for row in rows])
        axis.barh(labels, values, left=left, label=name, color=color); left += values
    axis.set_xlabel("Package 4 traced median (ms)"); axis.legend(ncol=4, frameon=False, fontsize=8)


def _render(rows, output):
    labels = ("Skull F14", "Skeleton F1", "Skull-skin F1")
    figure, axes = plt.subplots(2, 1, figsize=(12, 8), constrained_layout=True)
    _draw_totals(axes[0], rows, labels); _draw_phases(axes[1], rows, labels)
    axes[0].set_title("Fiber V2 Package 4 — production planner profile")
    figure.savefig(output, dpi=180); plt.close(figure)


def main():
    args = _arguments(); output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    _render(_load(args.inputs), output)


if __name__ == "__main__":
    main()

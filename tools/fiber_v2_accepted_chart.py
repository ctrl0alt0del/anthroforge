"""Create summary charts from accepted full-cycle benchmark JSON files."""

import argparse
import glob
import json
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True); return parser.parse_args()


def _records(pattern):
    paths = sorted(glob.glob(pattern)); return [(Path(path).stem, json.loads(Path(path).read_text())) for path in paths]


def _labels(rows):
    names = {"skeleton_fiber1": "Skeleton F1", "skull_fiber1": "Skull F1",
             "skull_fiber13": "Skull F13", "skull_fiber14": "Skull F14",
             "skull_fiber22": "Skull F22", "skull_fiber4": "Skull F4",
             "skull_fiber9": "Skull F9", "skull_skin_fiber1": "Skin F1"}
    return [names.get(name, name) for name, _record in rows]


def _values(rows, key, field="warm"):
    return np.asarray([row[key]["timing"][field]["median_ms"] for _name, row in rows])


def _bars(axis, x, values, labels, colors):
    width = .8 / len(values)
    for index, (data, label, color) in enumerate(zip(values, labels, colors)):
        axis.bar(x + (index - (len(values) - 1) / 2) * width, data, width, label=label, color=color)
    axis.legend(frameon=False, ncol=len(values)); axis.grid(axis="y", alpha=.2)


def _planner(axis, rows, x):
    _bars(axis, x, (_values(rows, "package41"), _values(rows, "package43")),
          ("Package 4.1", "Package 4.3"), ("#5686c5", "#10a6c9"))
    axis.set_title("Planner only — warm shared snapshot"); axis.set_ylabel("milliseconds")


def _solver(axis, rows, x):
    _bars(axis, x, tuple(_values(rows, key) for key in ("v1", "package51", "package61")),
          ("V1", "Package 5.1", "Package 6.1"), ("#e86f00", "#9452bd", "#d5b500"))
    axis.set_title("Complete solve + final validation — warm shared snapshot"); axis.set_ylabel("milliseconds")


def _cold(axis, rows, x):
    v1 = np.asarray([row["v1"]["timing"]["cold_ms"] for _name, row in rows])
    capture = np.asarray([row["capture_ms"] for _name, row in rows])
    p61 = np.asarray([row["package61"]["timing"]["cold_ms"] for _name, row in rows])
    axis.bar(x - .2, v1, .4, label="V1 cold", color="#e86f00")
    axis.bar(x + .2, capture, .4, label="V2 capture", color="#3d718b")
    axis.bar(x + .2, p61, .4, bottom=capture, label="P6.1 cold", color="#d5b500")
    axis.set_title("Single-Fiber cold full cycle"); axis.set_ylabel("milliseconds"); axis.legend(frameon=False, ncol=3)


def _chart(rows, output):
    labels = _labels(rows); x = np.arange(len(rows)); figure, axes = plt.subplots(3, 1, figsize=(15, 12), sharex=True)
    _planner(axes[0], rows, x); _solver(axes[1], rows, x); _cold(axes[2], rows, x)
    axes[2].set_xticks(x, labels, rotation=25, ha="right"); axes[2].grid(axis="y", alpha=.2)
    figure.suptitle("Fiber V1 vs accepted V2 packages — fresh Blender 5.0.1 processes")
    figure.tight_layout(); figure.savefig(output, dpi=180); plt.close(figure)


def main():
    args = _arguments(); rows = _records(args.input); Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    _chart(rows, args.output)


if __name__ == "__main__":
    main()

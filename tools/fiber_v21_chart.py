"""Create V1, Package 6.1, and V2.1 benchmark charts."""

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
    return [(Path(path).stem, json.loads(Path(path).read_text())) for path in sorted(glob.glob(pattern))]


def _labels(rows):
    names = {"skeleton_fiber1": "Skeleton F1", "skull_fiber1": "Skull F1",
             "skull_fiber13": "Skull F13", "skull_fiber14": "Skull F14",
             "skull_fiber22": "Skull F22", "skull_fiber4": "Skull F4",
             "skull_fiber9": "Skull F9", "skull_skin_fiber1": "Skin F1"}
    return [names.get(name, name) for name, _row in rows]


def _values(rows, key):
    return np.asarray([row[key]["timing"]["median_ms"] for _name, row in rows])


def _bars(axis, x, values, labels, colors):
    width = .8 / len(values)
    for index, (data, label, color) in enumerate(zip(values, labels, colors)):
        axis.bar(x + (index - (len(values) - 1) / 2) * width, data, width, label=label, color=color)
    axis.legend(frameon=False, ncol=len(values)); axis.grid(axis="y", alpha=.2)


def _steady(axis, rows, x):
    values = tuple(_values(rows, key) for key in ("v1", "package61", "v21"))
    _bars(axis, x, values, ("V1", "P6.1", "V2.1 exact reuse"), ("#e86f00", "#d5b500", "#13a56a"))
    axis.set_title("Warm complete solve + strict validation"); axis.set_ylabel("milliseconds")


def _edit(axis, rows, x):
    values = tuple(_values(rows, key) for key in ("package61_edit", "v21_edit"))
    _bars(axis, x, values, ("P6.1 property edit", "V2.1 validated corridor reuse"), ("#d5b500", "#13a56a"))
    axis.set_title("Sequential curvature-property edits"); axis.set_ylabel("milliseconds")


def _handle(axis, rows, x):
    values = tuple(_values(rows, key) for key in ("package61_handle", "v21_handle"))
    _bars(axis, x, values, ("P6.1 handle edits", "V2.1 corridor repair"), ("#d5b500", "#13a56a"))
    axis.set_title("Sequential small handle edits"); axis.set_ylabel("milliseconds")


def _chart(rows, output):
    labels = _labels(rows); x = np.arange(len(rows)); figure, axes = plt.subplots(3, 1, figsize=(15, 12), sharex=True)
    _steady(axes[0], rows, x); _edit(axes[1], rows, x); _handle(axes[2], rows, x)
    axes[2].set_xticks(x, labels, rotation=25, ha="right"); figure.suptitle("Fiber V2.1 hybrid experiment")
    figure.tight_layout(); figure.savefig(output, dpi=180); plt.close(figure)


def main():
    args = _arguments(); rows = _records(args.input); Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    _chart(rows, args.output)


if __name__ == "__main__":
    main()

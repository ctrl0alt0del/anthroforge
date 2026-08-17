"""Create V2.2 numeric and uncached-request timing charts."""

import argparse
import glob
import json
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from fiber_v21_chart import _bars, _labels


def _arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True); return parser.parse_args()


def _records(pattern):
    return [(Path(path).stem, json.loads(Path(path).read_text())) for path in sorted(glob.glob(pattern))]


def _values(rows, key):
    return np.asarray([row[key]["timing"]["median_ms"] for _name, row in rows])


def _live(rows, key):
    numeric = _values(rows, key)
    signature = np.asarray([row[key]["request_signature_timing"]["median_ms"] for _name, row in rows])
    return numeric + signature


def _baseline(axis, rows, x):
    values = tuple(_values(rows, key) for key in ("v1", "package61", "v21", "v22"))
    _bars(axis, x, values, ("V1", "P6.1", "V2.1", "V2.2"),
          ("#e86f00", "#d5b500", "#3b8edb", "#13a56a"))
    axis.set_title("Warm complete solve + strict validation"); axis.set_ylabel("milliseconds")


def _properties(axis, rows, x):
    values = (_live(rows, "v21_edit"), _values(rows, "v22_edit"))
    _bars(axis, x, values, ("V2.1 uncached request", "V2.2 compact request"), ("#3b8edb", "#13a56a"))
    axis.set_title("Sequential property edits, including request identity"); axis.set_ylabel("milliseconds")


def _handles(axis, rows, x):
    values = (_live(rows, "v21_handle"), _values(rows, "v22_preview"), _values(rows, "v22_final"))
    _bars(axis, x, values, ("V2.1 uncached preview", "V2.2 preview", "V2.2 fresh final"),
          ("#3b8edb", "#13a56a", "#7a4bc2"))
    axis.set_title("Sequential handle edits, including request identity"); axis.set_ylabel("milliseconds")


def _chart(rows, output):
    labels = _labels(rows); x = np.arange(len(rows)); figure, axes = plt.subplots(3, 1, figsize=(15, 12), sharex=True)
    _baseline(axes[0], rows, x); _properties(axes[1], rows, x); _handles(axes[2], rows, x)
    axes[2].set_xticks(x, labels, rotation=25, ha="right"); figure.suptitle("Fiber V2.2 integration experiment")
    figure.tight_layout(); figure.savefig(output, dpi=180); plt.close(figure)


def main():
    args = _arguments(); rows = _records(args.input); Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    _chart(rows, args.output)


if __name__ == "__main__":
    main()

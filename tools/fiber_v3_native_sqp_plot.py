"""Plot native legacy/indexed CCD controller trajectories from benchmark JSON."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("input"); parser.add_argument("fiber")
    parser.add_argument("output"); return parser.parse_args()


def _record(path, fiber):
    payload = json.loads(Path(path).read_text(encoding="utf-8")); key = fiber.upper()
    return next(row for row in payload["fibers"] if row["fiber"].upper() == key)


def _flatten(spans):
    rows, separators = [], []
    for span in spans:
        rows.extend(span); separators.append(len(rows))
    return rows, separators[:-1]


def _series(rows):
    safe = np.asarray([row[2] for row in rows]); accepted = np.asarray([row[1] == "ACCEPT" for row in rows])
    injected = np.asarray([row[1] == "INJECT" for row in rows]); return safe, accepted, injected


def _trajectory(axis, rows, label, color):
    safe, accepted, injected = _series(rows); x = np.arange(1, len(rows) + 1)
    axis.plot(x, safe, color=color, linewidth=.9, alpha=.9, label=label)
    axis.scatter(x[injected], safe[injected], color=color, marker="x", s=13)
    return np.cumsum(accepted)


def _decorate(axis, separators, title, ylabel):
    for value in separators: axis.axvline(value + .5, color="#64748b", linewidth=.6, alpha=.5)
    axis.set_title(title); axis.set_ylabel(ylabel); axis.grid(alpha=.18); axis.legend(loc="best")


def _plot(record, output):
    legacy, separators = _flatten(record["native_legacy"]["trajectory"])
    indexed, _unused = _flatten(record["native_indexed"]["trajectory"])
    figure, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True, constrained_layout=True)
    first = _trajectory(axes[0], legacy, "legacy serial CCD", "#06b6d4")
    second = _trajectory(axes[0], indexed, "indexed task CCD", "#ec4899")
    _decorate(axes[0], separators, f"{record['fiber']} CCD safe-step trajectory (x = limiter injection)", "safe fraction")
    axes[1].plot(np.arange(1, len(first) + 1), first, color="#06b6d4", label="legacy accepted")
    axes[1].plot(np.arange(1, len(second) + 1), second, color="#ec4899", label="indexed accepted")
    _decorate(axes[1], separators, "Controller progress", "cumulative accepted steps")
    axes[1].set_xlabel("native controller trial"); figure.savefig(output, dpi=160); plt.close(figure)


def main():
    args = _args(); output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _plot(_record(args.input, args.fiber), output); return 0


if __name__ == "__main__":
    raise SystemExit(main())

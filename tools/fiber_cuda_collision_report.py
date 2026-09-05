"""Render the isolated CUDA collision experiment report."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--benchmark", required=True)
    parser.add_argument("--all-open", required=True); parser.add_argument("--capture", required=True)
    parser.add_argument("--full-cycle", required=True); parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def series(rows, name):
    return np.asarray([row[name] for row in rows], dtype=np.float64)


def style_axis(axis):
    axis.grid(True, which="both", alpha=0.2); axis.set_xscale("log", base=2)
    axis.set_xlabel("Packed segment/triangle pairs"); axis.set_ylabel("Median wall time (ms)")


def plot_benchmark(benchmark, all_open, output):
    rows = list(benchmark["rows"]); rows.append(all_open["rows"][-1])
    rows = sorted({row["pairs"]: row for row in rows}.values(), key=lambda row: row["pairs"])
    pairs = series(rows, "pairs"); figure, axis = plt.subplots(figsize=(9.5, 5.4), dpi=160)
    axis.plot(pairs, series(rows, "cpu_total_ms"), "o-", label="CPU native + packing")
    axis.plot(pairs, series(rows, "cuda_dynamic_wall_ms"), "o-", label="CUDA dynamic pairs")
    axis.plot(pairs, series(rows, "cuda_cached_wall_ms"), "o-", label="CUDA cached pairs")
    axis.axvline(3131, color="#9b59b6", linestyle="--", label="Cranium batch: 3,131")
    style_axis(axis); axis.legend(); figure.tight_layout(); figure.savefig(output); plt.close(figure)


def full_summary(data):
    rows = [value["diagnostics"] for value in data["results"].values()]
    total = lambda name: sum(float(row[name]) for row in rows)
    return {"fibers": len(rows), "full_ms": data["full_cycle_ms"], "contact_ms": total("native_contact_ms"),
            "validation_ms": total("native_validation_ms"), "pairs": int(total("ccd_candidate_pairs")),
            "accepted": int(total("accepted_steps")), "rejected": int(total("rejected_steps"))}


def exact_row(benchmark):
    return benchmark["rows"][-1]


def result_lines(row, chart):
    ratio = row["cuda_cached_wall_ms"] / row["cpu_total_ms"]
    return ["# Fiber CUDA multi-Fiber collision experiment", "", "## Result", "",
            f"The production-shaped Cranium batch is **slower on CUDA**: `{row['cuda_cached_wall_ms']:.3f} ms` versus `{row['cpu_total_ms']:.3f} ms` on CPU ({ratio:.2f}× CPU time).",
            "", f"![CPU versus CUDA collision crossover]({chart.name})", ""]


def workload_lines(capture, row, all_row):
    return ["## Real workload", "",
            f"- Shortcut: `{capture['shortcut']}`; requested Fibers: {capture['requested']}; valid open V3 Fibers: {len(capture['fibers'])}.",
            f"- Packed geometry: {capture['segments']} segments, {capture['triangles']} triangles, {capture['pairs']} candidate pairs.",
            f"- CPU: `{row['cpu_total_ms']:.3f} ms`; CUDA dynamic: `{row['cuda_dynamic_wall_ms']:.3f} ms`; CUDA cached-pair: `{row['cuda_cached_wall_ms']:.3f} ms`.",
            f"- CUDA kernel alone: `{row['cuda_kernel_ms']:.3f} ms`; maximum CPU/CUDA distance error: `{row['max_abs_error']:.3e}`.",
            f"- All 21 open Fibers reach {all_row['pairs']} pairs; cached CUDA is `{all_row['cuda_cached_wall_ms']:.3f} ms` versus CPU `{all_row['cpu_total_ms']:.3f} ms`.", ""]


def context_lines(full):
    trials = full["accepted"] + full["rejected"]
    return ["## Full-cycle context", "",
            f"The 15-Fiber final V3 run took `{full['full_ms']:.1f} ms`. Recorded native contact work was `{full['contact_ms']:.1f} ms` ({100.0*full['contact_ms']/full['full_ms']:.1f}%); validation was `{full['validation_ms']:.1f} ms`.",
            f"Across {trials} solver trials it processed {full['pairs']:,} CCD candidates, about `{full['pairs']/trials:.1f}` per trial.", ""]


def interpretation_lines(capture):
    unchanged = capture["hash_before"] == capture["hash_after"]
    return ["## Interpretation", "",
            "The RTX 4080 computes the narrow-phase kernel faster once work is resident, but host/device synchronization and result transfer erase the gain at the actual 3,131-pair batch. Per-iteration work is much smaller still.",
            "CUDA would require the complete contact/CCD/controller state to stay on-device and substantially larger batches. Replacing only the current collision query would regress this workload.",
            "", "## Scope", "",
            "This experiment covers batched segment/triangle static distance queries with persistent triangle storage and optional persistent pair indices. It does not replace production V3, change Fiber output, or claim CUDA CCD parity.",
            f"The source blend remained byte-identical: `{unchanged}` (`{capture['hash_before']}`)."]


def markdown(capture, benchmark, all_open, full, chart):
    row = exact_row(benchmark); all_row = exact_row(all_open)
    lines = result_lines(row, chart) + workload_lines(capture, row, all_row)
    lines += context_lines(full) + interpretation_lines(capture)
    return "\n".join(lines) + "\n"


def main():
    args = arguments(); output = Path(args.output_dir); output.mkdir(parents=True, exist_ok=True)
    benchmark, all_open = load(args.benchmark), load(args.all_open)
    capture, full = load(args.capture), full_summary(load(args.full_cycle))
    chart = output / "cpu_cuda_crossover.png"; plot_benchmark(benchmark, all_open, chart)
    report = output / "REPORT.md"; report.write_text(markdown(capture, benchmark, all_open, full, chart), encoding="utf-8")
    print(report); return 0


if __name__ == "__main__":
    raise SystemExit(main())

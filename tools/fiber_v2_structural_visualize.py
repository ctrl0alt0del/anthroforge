"""Generate visual Package 2 comparisons from Blender benchmark JSON."""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


BG = (18, 22, 29)
PANEL = (28, 34, 44)
TEXT = (225, 232, 240)
MUTED = (148, 160, 175)
ORANGE = (255, 151, 63)
CYAN = (42, 211, 219)
PURPLE = (174, 126, 255)
GREEN = (102, 222, 135)
WHITE = (255, 255, 255)


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", nargs="+", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def _records(paths):
    return [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]


def _font(size=18):
    candidates = ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf")
    path = next((item for item in candidates if Path(item).exists()), None)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()


def _projection(original, solved):
    combined = np.vstack((original, solved)); centered = combined - combined.mean(axis=0)
    _u, _s, axes = np.linalg.svd(centered, full_matrices=False)
    projected = centered @ axes[:2].T
    return projected[:len(original)], projected[len(original):]


def _mapped(points, rect):
    x0, y0, x1, y1 = rect; mins, spans = points.min(axis=0), np.ptp(points, axis=0)
    scale = min((x1 - x0) / max(spans[0], 1e-12), (y1 - y0) / max(spans[1], 1e-12))
    centered = points - (mins + spans / 2.0)
    return [(x0 + (x1 - x0) / 2 + p[0] * scale,
             y0 + (y1 - y0) / 2 - p[1] * scale) for p in centered]


def _panel_points(record, rect):
    visual = record["visual"]
    original, solved = np.asarray(visual["input"]), np.asarray(visual["structural"])
    first, second = _projection(original, solved)
    combined = np.vstack((first, second)); mapped = _mapped(combined, rect)
    return mapped[:len(first)], mapped[len(first):], first, visual


def _draw_pin(draw, point):
    x, y = point
    draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=WHITE, outline=BG, width=2)


def _draw_panel(draw, record, rect):
    draw.rounded_rectangle(rect, radius=18, fill=PANEL)
    plot = (rect[0] + 35, rect[1] + 105, rect[2] - 35, rect[3] - 70)
    original, solved, projected, visual = _panel_points(record, plot)
    cyclic = record["topology"] == "CYCLIC"
    draw.line(_closed(original, cyclic), fill=ORANGE, width=6, joint="curve")
    draw.line(_closed(solved, cyclic), fill=CYAN, width=4, joint="curve")
    _draw_pins(draw, original, projected, visual)
    _draw_panel_text(draw, record, rect)


def _closed(points, cyclic):
    return points + points[:1] if cyclic else points


def _draw_pins(draw, original, projected, visual):
    source = np.asarray(visual["input"]); pins = np.asarray(visual["pins"])
    for pin in pins:
        index = int(np.argmin(np.linalg.norm(source - pin, axis=1)))
        _draw_pin(draw, original[index])


def _draw_panel_text(draw, record, rect):
    count = str(record["stored_count"]); metrics = record["counts"][count]
    title = f"{Path(record['file']).name}  /  {record['fiber_id']}"
    detail = (f"N={count}   warm {metrics['warm']['median_ms']:.3f} ms   "
              f"max move {metrics['max_displacement']:.4g}")
    draw.text((rect[0] + 32, rect[1] + 25), title, font=_font(25), fill=TEXT)
    draw.text((rect[0] + 32, rect[1] + 62), detail, font=_font(17), fill=MUTED)


def _overlay(records, output):
    image = Image.new("RGB", (1600, 900), BG); draw = ImageDraw.Draw(image)
    draw.text((50, 30), "Fiber V2 Package 2 — structural objective", font=_font(32), fill=TEXT)
    draw.text((50, 72), "Orange: persisted Blender curve   Cyan: structural minimizer   White: hard pins",
              font=_font(18), fill=MUTED)
    width = (1500 - 30 * (len(records) - 1)) / len(records)
    for index, record in enumerate(records):
        x0 = 50 + index * (width + 30)
        _draw_panel(draw, record, (x0, 120, x0 + width, 840))
    image.save(output)


def _chart_axes(draw, rect, max_ms):
    x0, y0, x1, y1 = rect
    draw.line((x0, y1, x1, y1), fill=MUTED, width=2)
    draw.line((x0, y0, x0, y1), fill=MUTED, width=2)
    for fraction in np.linspace(0.0, 1.0, 5):
        y = y1 - fraction * (y1 - y0)
        draw.line((x0, y, x1, y), fill=(48, 56, 68), width=1)
        draw.text((x0 - 70, y - 10), f"{fraction * max_ms:.2f}", font=_font(14), fill=MUTED)


def _series(record, key):
    rows = sorted((int(count), values[key]["median_ms"])
                  for count, values in record["counts"].items())
    return rows


def _chart_points(rows, rect, max_ms):
    x0, y0, x1, y1 = rect; counts = [item[0] for item in rows]
    return [(x0 + i * (x1 - x0) / max(1, len(rows) - 1),
             y1 - value * (y1 - y0) / max_ms) for i, (_count, value) in enumerate(rows)], counts


def _draw_series(draw, record, key, color, rect, max_ms, label_y):
    points, counts = _chart_points(_series(record, key), rect, max_ms)
    draw.line(points, fill=color, width=4, joint="curve")
    for point, count in zip(points, counts):
        draw.ellipse((point[0] - 5, point[1] - 5, point[0] + 5, point[1] + 5), fill=color)
        draw.text((point[0] - 12, rect[3] + 12), str(count), font=_font(14), fill=MUTED)
    draw.text((rect[2] - 290, label_y), f"{record['fiber_id']} {key}", font=_font(16), fill=color)


def _benchmark_chart(records, output):
    image = Image.new("RGB", (1400, 850), BG); draw = ImageDraw.Draw(image)
    draw.text((55, 35), "Structural solve scaling on persisted Blender Fibers", font=_font(30), fill=TEXT)
    rect = (140, 140, 1320, 710); maximum = _maximum_ms(records)
    _chart_axes(draw, rect, maximum)
    colors = ((ORANGE, (255, 205, 118)), (CYAN, (126, 238, 243)),
              (PURPLE, (213, 186, 255)), (GREEN, (178, 245, 195)))
    for index, record in enumerate(records):
        _draw_series(draw, record, "cold", colors[index][0], rect, maximum, 75 + 24 * index)
        _draw_series(draw, record, "warm", colors[index][1], rect, maximum, 75 + 24 * (index + len(records)))
    draw.text((55, 790), "Node count →     Median milliseconds; includes Python wrapper and XYZ solve",
              font=_font(17), fill=MUTED)
    image.save(output)


def _maximum_ms(records):
    values = [row[key]["median_ms"] for record in records
              for row in record["counts"].values() for key in ("cold", "warm")]
    return max(values) * 1.15


def main():
    args = _arguments(); records = _records(args.inputs)
    output = Path(args.output_dir); output.mkdir(parents=True, exist_ok=True)
    _overlay(records, output / "real_file_structural_overlay.png")
    _benchmark_chart(records, output / "structural_benchmark_scaling.png")


if __name__ == "__main__":
    main()

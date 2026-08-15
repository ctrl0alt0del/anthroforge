"""Render Package 3 real-file clearance previews and benchmarks."""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


BG = (17, 21, 28); PANEL = (27, 33, 43); TEXT = (231, 236, 243); MUTED = (150, 161, 176)
GREEN = (70, 225, 137); RED = (255, 82, 82); MESH = (76, 87, 103); CYAN = (55, 205, 227)


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", nargs="+", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def _font(size):
    paths = ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf")
    path = next((item for item in paths if Path(item).exists()), None)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()


def _projection(points, triangles):
    cloud = np.vstack((points, triangles.reshape((-1, 3)))) if len(triangles) else points
    centered = cloud - points.mean(axis=0); _u, _s, axes = np.linalg.svd(points - points.mean(axis=0), full_matrices=False)
    return centered @ axes[:2].T, centered @ axes[2]


def _mapped(points, rect):
    low, span = points.min(axis=0), np.ptp(points, axis=0)
    scale = min((rect[2] - rect[0]) / max(span[0], 1e-9), (rect[3] - rect[1]) / max(span[1], 1e-9))
    center = low + span / 2.0
    return np.column_stack((rect[0] + (rect[2] - rect[0]) / 2 + (points[:, 0] - center[0]) * scale,
                            rect[1] + (rect[3] - rect[1]) / 2 - (points[:, 1] - center[1]) * scale))


def _panel_geometry(record, rect):
    visual = record["visual"]; points = np.asarray(visual["points"])
    triangles = np.asarray(visual["nearby_triangles"])
    projected, depth = _projection(points, triangles)
    mapped = _mapped(projected, rect); count = len(points)
    return mapped[:count], mapped[count:].reshape((-1, 3, 2)), depth[count:].reshape((-1, 3))


def _draw_mesh(draw, triangles, depth):
    order = np.argsort(depth.mean(axis=1)) if len(triangles) else ()
    for index in order:
        points = [tuple(value) for value in triangles[index]]
        draw.polygon(points, fill=(39, 47, 60), outline=MESH)


def _draw_fiber(draw, points, violating):
    for index in range(len(points) - 1):
        color = RED if index in violating else GREEN
        draw.line((tuple(points[index]), tuple(points[index + 1])), fill=(8, 10, 14), width=8)
        draw.line((tuple(points[index]), tuple(points[index + 1])), fill=color, width=5)
    for point in (points[0], points[-1]):
        draw.ellipse((point[0] - 6, point[1] - 6, point[0] + 6, point[1] + 6), fill=CYAN)


def _draw_panel(draw, record, rect):
    draw.rounded_rectangle(rect, radius=18, fill=PANEL)
    plot = (rect[0] + 25, rect[1] + 115, rect[2] - 25, rect[3] - 55)
    points, triangles, depth = _panel_geometry(record, plot)
    _draw_mesh(draw, triangles, depth)
    violating = _invalid_edges(record, len(points)); _draw_fiber(draw, points, violating)
    _panel_text(draw, record, rect, len(violating))


def _invalid_edges(record, count):
    row = record["counts"][str(record["stored_count"])]["static"]
    edges = set(row["violating_edges"])
    for node in row.get("contained_nodes", ()):
        if node > 0:
            edges.add(node - 1)
        if node + 1 < count:
            edges.add(node)
    return edges


def _panel_text(draw, record, rect, violations):
    count = str(record["stored_count"]); row = record["counts"][count]["static"]
    title = f"{Path(record['file']).name} / {record['fiber_id']}"
    detail = f"{row['reason']}   red edges {violations}   static {row['timing']['median_ms']:.2f} ms"
    mesh = f"{record['triangles']:,} triangles   radius {record['collision_radius']:.4g} BU"
    draw.text((rect[0] + 25, rect[1] + 22), title, font=_font(24), fill=TEXT)
    draw.text((rect[0] + 25, rect[1] + 57), detail, font=_font(16), fill=RED if violations else GREEN)
    draw.text((rect[0] + 25, rect[1] + 82), mesh, font=_font(15), fill=MUTED)


def _preview(records, output):
    width = max(520, int((1580 - 40 * (len(records) - 1)) / len(records)))
    image = Image.new("RGB", (100 + len(records) * width + (len(records) - 1) * 40, 900), BG)
    draw = ImageDraw.Draw(image)
    draw.text((50, 25), "Fiber V2 Package 3 — native static clearance on real Blender Fibers", font=_font(30), fill=TEXT)
    draw.text((50, 67), "Green: validated edge   Red: clearance violation   Gray: nearby evaluated collider triangles", font=_font(17), fill=MUTED)
    for index, record in enumerate(records):
        x = 50 + index * (width + 40); _draw_panel(draw, record, (x, 110, x + width, 850))
    image.save(output)


def _series(record, mode):
    return sorted((int(count), row[mode]["timing"]["median_ms"])
                  for count, row in record["counts"].items())


def _chart(records, output):
    image = Image.new("RGB", (1400, 850), BG); draw = ImageDraw.Draw(image)
    draw.text((55, 35), "Package 3 collision scaling — native backend", font=_font(30), fill=TEXT)
    rect = (135, 145, 1320, 710); maximum = _max_timing(records) * 1.15
    _axes(draw, rect, maximum)
    colors = ((GREEN, CYAN), (RED, (255, 165, 82)), ((181, 125, 255), (222, 180, 255)))
    for index, record in enumerate(records):
        _draw_series(draw, record, "static", colors[index][0], rect, maximum, 75 + 23 * index)
        _draw_series(draw, record, "ccd_probe", colors[index][1], rect, maximum, 75 + 23 * (index + len(records)))
    draw.text((55, 790), "Node count →     Median milliseconds including broad phase, local owner filter, and native narrow phase",
              font=_font(17), fill=MUTED)
    image.save(output)


def _axes(draw, rect, maximum):
    draw.line((rect[0], rect[3], rect[2], rect[3]), fill=MUTED, width=2)
    draw.line((rect[0], rect[1], rect[0], rect[3]), fill=MUTED, width=2)
    for fraction in np.linspace(0.0, 1.0, 5):
        y = rect[3] - fraction * (rect[3] - rect[1])
        draw.line((rect[0], y, rect[2], y), fill=(47, 55, 67), width=1)
        draw.text((rect[0] - 75, y - 9), f"{fraction * maximum:.1f}", font=_font(13), fill=MUTED)


def _draw_series(draw, record, mode, color, rect, maximum, label_y):
    rows = _series(record, mode); points = []
    for index, (count, value) in enumerate(rows):
        x = rect[0] + index * (rect[2] - rect[0]) / max(1, len(rows) - 1)
        y = rect[3] - value * (rect[3] - rect[1]) / maximum; points.append((x, y))
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=color)
        draw.text((x - 14, rect[3] + 12), str(count), font=_font(13), fill=MUTED)
    draw.line(points, fill=color, width=4)
    draw.text((rect[2] - 330, label_y), f"{record['fiber_id']} {mode}", font=_font(15), fill=color)


def _max_timing(records):
    return max(row[mode]["timing"]["median_ms"] for record in records
               for row in record["counts"].values() for mode in ("static", "ccd_probe"))


def main():
    args = _arguments(); records = [json.loads(Path(path).read_text(encoding="utf-8")) for path in args.inputs]
    output = Path(args.output_dir); output.mkdir(parents=True, exist_ok=True)
    _preview(records, output / "real_file_collision_preview.png")
    _chart(records, output / "collision_benchmark_scaling.png")


if __name__ == "__main__":
    main()

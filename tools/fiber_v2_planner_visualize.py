"""Render Package 4 planner previews and benchmark comparison."""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


BG = (17, 21, 28); PANEL = (27, 33, 43); TEXT = (231, 236, 243); MUTED = (150, 161, 176)
GREEN = (70, 225, 137); ORANGE = (255, 171, 64); RED = (255, 82, 82); CYAN = (55, 205, 227)


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", nargs="+", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def _font(size):
    paths = ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf")
    path = next((item for item in paths if Path(item).exists()), None)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()


def _load(paths):
    return [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]


def _cloud(record):
    visual = record["visual"]
    routes = [np.asarray(visual[key]) for key in ("v1", "v2_corridor", "v2_reference")]
    triangles = np.asarray(visual["nearby_triangles"])
    return routes, triangles


def _project(record):
    routes, triangles = _cloud(record); route_cloud = np.vstack([row for row in routes if len(row)])
    mesh = triangles.reshape((-1, 3)) if len(triangles) else np.empty((0, 3))
    center = route_cloud.mean(axis=0); _u, _s, axes = np.linalg.svd(route_cloud - center, full_matrices=False)
    projected = [(row - center) @ axes[:2].T for row in routes]
    return projected, (mesh - center) @ axes[:2].T


def _mapping(rows, mesh, rect):
    cloud = np.vstack((*rows, mesh)) if len(mesh) else np.vstack(rows)
    low, span = cloud.min(axis=0), np.ptp(cloud, axis=0)
    scale = min((rect[2] - rect[0]) / max(span[0], 1e-9), (rect[3] - rect[1]) / max(span[1], 1e-9))
    center = low + span / 2.0
    transform = lambda values: np.column_stack((rect[0] + (rect[2] - rect[0]) / 2 + (values[:, 0] - center[0]) * scale,
                                                 rect[1] + (rect[3] - rect[1]) / 2 - (values[:, 1] - center[1]) * scale))
    return [transform(row) for row in rows], transform(mesh)


def _draw_mesh(draw, mesh):
    triangles = mesh.reshape((-1, 3, 2))
    for face in triangles:
        draw.polygon([tuple(point) for point in face], fill=(38, 45, 57), outline=(67, 78, 94))


def _draw_route(draw, points, color, width, violations=()):
    for index, (first, second) in enumerate(zip(points[:-1], points[1:])):
        value = RED if index in violations else color
        draw.line((tuple(first), tuple(second)), fill=(8, 10, 14), width=width + 4)
        draw.line((tuple(first), tuple(second)), fill=value, width=width)


def _draw_anchors(draw, reference, indices):
    for index in indices:
        point = reference[int(index)]
        draw.ellipse((point[0] - 6, point[1] - 6, point[0] + 6, point[1] + 6), fill=CYAN)


def _panel_text(draw, record, rect):
    v1, v2 = record["v1"], record["v2"]
    title = f"{Path(record['file']).name} / {record['fiber_id']}"
    line1 = f"V1 {v1['timing']['median_ms']:.1f} ms — {'VALID' if v1['validation']['valid'] else 'UNSAFE'}"
    line2 = f"Package 4 {v2['timing']['median_ms']:.1f} ms — {v2['termination']} / {v2['mode']}"
    detail = f"{record['triangles']:,} tris   corridor {v2['route']['count']} pts   exact {v2['reference']['count']} pts"
    draw.text((rect[0] + 22, rect[1] + 18), title, font=_font(22), fill=TEXT)
    draw.text((rect[0] + 22, rect[1] + 50), line1, font=_font(16), fill=GREEN if v1["validation"]["valid"] else RED)
    draw.text((rect[0] + 22, rect[1] + 75), line2, font=_font(16), fill=GREEN)
    draw.text((rect[0] + 22, rect[1] + 100), detail, font=_font(14), fill=MUTED)


def _draw_panel(draw, record, rect):
    draw.rounded_rectangle(rect, radius=18, fill=PANEL); plot = (rect[0] + 18, rect[1] + 140, rect[2] - 18, rect[3] - 42)
    rows, mesh = _project(record); mapped, mesh = _mapping(rows, mesh, plot)
    _draw_mesh(draw, mesh); _draw_route(draw, mapped[0], ORANGE, 3, record["v1"]["validation"]["violating_edges"])
    _draw_route(draw, mapped[2], GREEN, 2); _draw_route(draw, mapped[1], GREEN, 5)
    _draw_anchors(draw, mapped[2], record["v2"]["pin_indices"]); _panel_text(draw, record, rect)


def _preview(records, output):
    width = 560; image = Image.new("RGB", (80 + len(records) * (width + 25), 840), BG); draw = ImageDraw.Draw(image)
    draw.text((40, 20), "Fiber V2 Package 4 — deterministic planner previews", font=_font(29), fill=TEXT)
    draw.text((40, 58), "Orange/red: V1 route   Green: Package 4 safe corridor + exact-count handoff   Cyan: authored pins", font=_font(16), fill=MUTED)
    for index, record in enumerate(records):
        left = 40 + index * (width + 25); _draw_panel(draw, record, (left, 95, left + width, 800))
    image.save(output)


def _bar(draw, x, base, width, value, maximum, color):
    height = 430.0 * value / maximum
    draw.rounded_rectangle((x, base - height, x + width, base), radius=8, fill=color)
    draw.text((x, base - height - 27), f"{value:.1f}", font=_font(14), fill=color)


def _chart(records, output):
    image = Image.new("RGB", (1450, 760), BG); draw = ImageDraw.Draw(image)
    draw.text((50, 28), "Package 4 planner — real Blender median wall time", font=_font(30), fill=TEXT)
    maximum = max(record[key]["timing"]["median_ms"] for record in records for key in ("v1", "v2")) * 1.12
    base, group = 620, 410
    for index, record in enumerate(records):
        x = 120 + index * group; _bar(draw, x, base, 95, record["v1"]["timing"]["median_ms"], maximum, ORANGE)
        _bar(draw, x + 115, base, 95, record["v2"]["timing"]["median_ms"], maximum, GREEN)
        label = f"{Path(record['file']).stem}\n{record['fiber_id']}"
        draw.multiline_text((x - 5, base + 25), label, font=_font(15), fill=TEXT, spacing=4)
    draw.text((50, 705), "Orange: V1 planner   Green: Package 4 (unified strict collision + exact-count validation)", font=_font(17), fill=MUTED)
    image.save(output)


def main():
    args = _arguments(); records = _load(args.inputs); output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _preview(records, output / "real_file_planner_preview.png")
    _chart(records, output / "planner_benchmark_comparison.png")


if __name__ == "__main__":
    main()

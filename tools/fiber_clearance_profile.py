"""Plot signed Fiber clearance in collision-radius units without matplotlib."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import numpy as np


SIZE = (2080, 800)
PLOT = (120, 80, 2020, 700)


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True); return parser.parse_args()


def _font(size):
    path = Path("C:/Windows/Fonts/segoeui.ttf")
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def _xy(x, y):
    left, top, right, bottom = PLOT
    return left + float(x) * (right - left), bottom - (float(y) + 4.0) * (bottom - top) / 8.0


def _background(draw):
    left, top, right, bottom = PLOT
    draw.rectangle((left, top, right, _xy(0, 1)[1]), fill="#eef9f1")
    draw.rectangle((left, _xy(0, 1)[1], right, _xy(0, 0)[1]), fill="#fff7e9")
    draw.rectangle((left, _xy(0, 0)[1], right, bottom), fill="#fff0ef")


def _grid(draw):
    for value in range(-4, 5):
        y = _xy(0, value)[1]
        color = "#2ecc71" if value == 1 else "#e74c3c" if value == 0 else "#c7ccd1"
        draw.line((PLOT[0], y, PLOT[2], y), fill=color, width=3 if value in (0, 1) else 1)
        draw.text((48, y - 13), str(value), fill="#242a30", font=_font(22))
    _x_grid(draw)


def _x_grid(draw):
    for value in range(0, 101, 10):
        x = _xy(value / 100.0, 0)[0]
        draw.line((x, PLOT[1], x, PLOT[3]), fill="#d7dce0", width=1)
        draw.text((x - 12, PLOT[3] + 12), str(value), fill="#242a30", font=_font(18))


def _curve(draw, row, color, width):
    values = zip(np.asarray(row["arc"]), np.clip(np.asarray(row["ratio"]), -4.0, 4.0))
    points = [_xy(x, y) for x, y in values]
    if len(points) > 1:
        draw.line(points, fill=color, width=width, joint="curve")


def _pins(draw, record):
    arcs = np.asarray(record["corrected"]["arc"])
    for index in np.asarray(record["pin_indices"], dtype=int):
        x = _xy(arcs[index], 0)[0]
        draw.line((x, PLOT[1], x, PLOT[3]), fill="#d4ac0d", width=2)


def _labels(draw, record):
    title = f'{record["fiber"]}: signed nearest-surface clearance'
    draw.text((SIZE[0] // 2 - 270, 18), title, fill="#161b20", font=_font(30))
    draw.text((840, 745), "Fiber arclength (%)", fill="#242a30", font=_font(24))
    draw.text((1500, 95), "orange stored V1   green corrected", fill="#242a30", font=_font(22))


def _render(record, output):
    image = Image.new("RGB", SIZE, "white"); draw = ImageDraw.Draw(image)
    _background(draw); _grid(draw); _pins(draw, record)
    _curve(draw, record["stored"], "#f39c12", 5)
    _curve(draw, record["corrected"], "#2ecc71", 5); _labels(draw, record)
    image.save(output)


def main():
    args = _args(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    _render(record, args.output)


if __name__ == "__main__":
    main()

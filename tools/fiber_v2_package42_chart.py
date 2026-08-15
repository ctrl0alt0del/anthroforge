"""Render the Package 4.2 persistent-BVH benchmark chart."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True); parser.add_argument("--output", required=True)
    return parser.parse_args()


def _font(size):
    path = Path("C:/Windows/Fonts/segoeui.ttf")
    return ImageFont.truetype(path, size) if path.exists() else ImageFont.load_default()


def _values(record):
    return [record["planners"][name]["timing"]["median_ms"]
            for name in ("package4", "package41", "package42")]


def _bar(draw, x, value, maximum, color):
    height = 440.0 * value / maximum; draw.rounded_rectangle((x, 600-height, x+110, 600), 10, fill=color)
    draw.text((x, 565-height), f"{value:.0f} ms", font=_font(18), fill=color)


def _group(draw, index, before, after, maximum):
    left = 150 + index * 430; _bar(draw, left, before, maximum, (255, 158, 70))
    _bar(draw, left + 135, after, maximum, (67, 211, 146))
    name = ("Package 4", "Package 4.1", "Package 4.2")[index]
    reduction = 100.0 * (before - after) / before
    draw.text((left, 625), name, font=_font(21), fill=(235, 240, 248))
    draw.text((left, 655), f"BVH reduction {reduction:.1f}%", font=_font(17), fill=(67, 211, 146))


def main():
    args = _arguments(); before = _values(json.loads(Path(args.before).read_text()))
    after = _values(json.loads(Path(args.after).read_text())); maximum = max(before) * 1.1
    image = Image.new("RGB", (1450, 760), (17, 21, 28)); draw = ImageDraw.Draw(image)
    draw.text((50, 30), "Package 4.2 — Maxilla/FIBER_21 collision acceleration", font=_font(31), fill=(235, 240, 248))
    draw.text((50, 75), "Orange: pre-BVH baseline   Green: persistent native BVH", font=_font(19), fill=(165, 176, 191))
    for index, (old, new) in enumerate(zip(before, after)):
        _group(draw, index, old, new, maximum)
    image.save(args.output)


if __name__ == "__main__":
    main()

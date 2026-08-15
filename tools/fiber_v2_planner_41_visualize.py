"""Build the Package 4.1 real-file benchmark chart."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BG = (17, 21, 28); TEXT = (231, 236, 243); MUTED = (150, 161, 176)
COLORS = ((255, 171, 64), (70, 225, 137), (55, 160, 255))


def _arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--inputs", nargs="+", required=True)
    parser.add_argument("--output", required=True); return parser.parse_args()


def _font(size):
    path = Path("C:/Windows/Fonts/segoeui.ttf")
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def _records(paths):
    return [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]


def _bar(draw, x, base, width, value, maximum, color):
    height = 420 * value / maximum; draw.rounded_rectangle((x, base - height, x + width, base), radius=7, fill=color)
    draw.text((x, base - height - 25), f"{value:.0f}", font=_font(13), fill=color)


def _group(draw, record, index, maximum):
    x, base = 85 + index * 350, 610; keys = ("v1", "package4", "package41")
    for offset, (key, color) in enumerate(zip(keys, COLORS)):
        _bar(draw, x + offset * 82, base, 65, record[key]["timing"]["median_ms"], maximum, color)
    label = f"{Path(record['file']).stem}\n{record['fiber_id']}"
    draw.multiline_text((x, base + 24), label, font=_font(14), fill=TEXT, spacing=4)


def _chart(records, output):
    image = Image.new("RGB", (1450, 735), BG); draw = ImageDraw.Draw(image)
    draw.text((45, 25), "Fiber planner — real Blender median wall time (ms)", font=_font(29), fill=TEXT)
    maximum = 1.12 * max(row[key]["timing"]["median_ms"] for row in records for key in ("v1", "package4", "package41"))
    for index, record in enumerate(records):
        _group(draw, record, index, maximum)
    draw.text((45, 695), "Orange V1   Green Package 4   Blue Package 4.1 cached-metric A*", font=_font(17), fill=MUTED)
    image.save(output)


def main():
    args = _arguments(); output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    _chart(_records(args.inputs), output)


if __name__ == "__main__":
    main()

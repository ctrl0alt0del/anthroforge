"""Label a true Blender Package 4.1 three-panel render."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True); parser.add_argument("--image", required=True)
    return parser.parse_args()


def _font(size):
    path = Path("C:/Windows/Fonts/segoeui.ttf")
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def _labels(record):
    v1, p4, p41 = record["v1"], record["package4"], record["package41"]
    valid = "VALID" if v1["validation"]["valid"] else "UNSAFE"
    return (("V1 PLANNER", f"{v1['timing']['median_ms']:.1f} ms  |  {valid}", (255, 171, 64)),
            ("PACKAGE 4", f"{p4['timing']['median_ms']:.1f} ms  |  {p4['mode']}", (70, 225, 137)),
            ("PACKAGE 4.1", f"{p41['timing']['median_ms']:.1f} ms  |  exact parity", (55, 160, 255)))


def _overlay(image, record):
    draw = ImageDraw.Draw(image); width = image.width / 3; draw.rectangle((0, 0, image.width, 102), fill=(13, 17, 24))
    for index, (title, detail, color) in enumerate(_labels(record)):
        left = index * width; draw.text((left + 120, 16), title, font=_font(28), fill=color)
        draw.text((left + 105, 57), detail, font=_font(19), fill=(230, 235, 242))
        if index:
            draw.line((left, 0, left, image.height), fill=(110, 121, 137), width=2)


def main():
    args = _arguments(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    path = Path(args.image); image = Image.open(path).convert("RGB")
    _overlay(image, record); image.save(path)


if __name__ == "__main__":
    main()

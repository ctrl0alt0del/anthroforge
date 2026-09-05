"""Add labels to a Blender-rendered Package 4 comparison."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--image", required=True)
    return parser.parse_args()


def _font(size):
    path = Path("C:/Windows/Fonts/segoeui.ttf")
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def _details(record):
    v1, v2 = record["v1"], record["v2"]
    left = f"{v1['timing']['median_ms']:.1f} ms  |  {'VALID' if v1['validation']['valid'] else 'UNSAFE'}"
    right = f"{v2['timing']['median_ms']:.1f} ms  |  {v2['termination']}  |  exact {v2['reference']['count']}"
    return left, right


def _overlay(image, record):
    draw = ImageDraw.Draw(image); left, right = _details(record)
    draw.rectangle((0, 0, image.width, 102), fill=(13, 17, 24))
    draw.text((205, 18), "V1 PLANNER", font=_font(30), fill=(255, 171, 64))
    draw.text((1120, 18), "PACKAGE 4", font=_font(30), fill=(70, 225, 137))
    draw.text((205, 58), left, font=_font(20), fill=(230, 235, 242))
    draw.text((1070, 58), right, font=_font(20), fill=(230, 235, 242))
    draw.line((900, 0, 900, image.height), fill=(110, 121, 137), width=2)


def main():
    args = _arguments(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    path = Path(args.image); image = Image.open(path).convert("RGB")
    _overlay(image, record); image.save(path)


if __name__ == "__main__":
    main()

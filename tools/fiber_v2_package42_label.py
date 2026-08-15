"""Add explanatory labels to the Package 4.2 Blender render."""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--image", required=True)
    return parser.parse_args()


def _font(size):
    path = Path("C:/Windows/Fonts/segoeui.ttf")
    return ImageFont.truetype(path, size) if path.exists() else ImageFont.load_default()


def _label(image, draw, index, text):
    width = image.width // 3; left, right = index * width + 20, (index + 1) * width - 20
    draw.rounded_rectangle((left, 18, right, 68), 12, fill=(12, 17, 24))
    draw.text((left + 18, 30), text, font=_font(22), fill=(255, 220, 220))


def main():
    args = _arguments(); image = Image.open(args.image).convert("RGB"); draw = ImageDraw.Draw(image)
    labels = ("V1 — ROLLED BACK / UNSAFE", "PACKAGE 4 — NO FEASIBLE PATH",
              "PACKAGE 4.2 — HARD PINS BLOCKED")
    for index, label in enumerate(labels):
        _label(image, draw, index, label)
    image.save(args.image)


if __name__ == "__main__":
    main()

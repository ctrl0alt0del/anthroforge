"""Build a labeled visual QA sheet from Fiber clearance renders."""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", required=True); return parser.parse_args()


def _font(size):
    path = "C:/Windows/Fonts/segoeui.ttf"
    return ImageFont.truetype(path, size) if Path(path).exists() else ImageFont.load_default()


def _fit(path, size):
    image = Image.open(path).convert("RGB"); image.thumbnail(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, "#17191d"); offset = ((size[0] - image.width) // 2, (size[1] - image.height) // 2)
    canvas.paste(image, offset); return canvas


def _paste(sheet, source, box, title):
    sheet.paste(_fit(source, (box[2], box[3])), (box[0], box[1]))
    ImageDraw.Draw(sheet).text((box[0] + 14, box[1] + 10), title, fill="white", font=_font(25))


def _header(sheet):
    draw = ImageDraw.Draw(sheet); draw.text((32, 22), "FIBER_2 clearance validation", fill="white", font=_font(38))
    legend = "orange stored V1 | green corrected centerline | blue required-radius shell | red/gray collider"
    draw.text((32, 72), legend, fill="#d8dde6", font=_font(23))


def _closeups(sheet, root):
    names = ("16", "31", "46"); width = 640
    for column, name in enumerate(names):
        source = root / f"clearance_close_node_{name}.png"; box = (32 + column * 656, 725, width, 480)
        _paste(sheet, source, box, f"true-scale local profile: node {name}")


def _build(root):
    sheet = Image.new("RGB", (2000, 1835), "#17191d"); _header(sheet)
    _paste(sheet, root / "stored_vs_guarded_side.png", (32, 120, 952, 570), "anatomical side comparison")
    _paste(sheet, root / "clearance_diagnostic_side.png", (1016, 120, 952, 570), "measured clearance overview")
    _closeups(sheet, root); _paste(sheet, root / "clearance_profile.png", (32, 1235, 1936, 568), "node clearance profile (full edge validation separate)")
    return sheet


def main():
    args = _args(); root = Path(args.input_dir); _build(root).save(args.output)


if __name__ == "__main__":
    main()

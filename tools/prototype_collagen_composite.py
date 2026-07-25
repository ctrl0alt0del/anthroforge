import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--fair", required=True)
    parser.add_argument("--strong", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def font():
    return ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 22)


def load(path):
    return Image.open(path).convert("RGBA")


def opaque(image):
    background = Image.new("RGBA", image.size, (13, 16, 22, 255))
    return Image.alpha_composite(background, image)


def overlay(structure, skin):
    alpha = skin.getchannel("A").point(lambda value: int(value * 0.48))
    transparent = skin.copy()
    transparent.putalpha(alpha)
    return Image.alpha_composite(opaque(structure), transparent)


def labeled(image, label):
    panel = Image.new("RGBA", (image.width, image.height + 44), (13, 16, 22, 255))
    panel.paste(image, (0, 44))
    ImageDraw.Draw(panel).text((16, 9), label, fill=(235, 240, 248, 255), font=font())
    return panel


def sheet(panels, columns=3):
    width, height = panels[0].size
    rows = (len(panels) + columns - 1) // columns
    result = Image.new("RGBA", (width * columns, height * rows), (13, 16, 22, 255))
    for index, panel in enumerate(panels):
        result.paste(panel, ((index % columns) * width, (index // columns) * height))
    return result


def variant_paths(args, view):
    return [
        ("Rolling probe", Path(args.base) / f"balanced_{view}.png"),
        ("Collagen 7 cm", Path(args.fair) / f"collagen_7cm_{view}.png"),
        ("Collagen 10 cm", Path(args.fair) / f"collagen_10cm_{view}.png"),
        ("Collagen 14 cm", Path(args.strong) / f"collagen_14cm_{view}.png"),
        ("Collagen 18 cm", Path(args.strong) / f"collagen_18cm_{view}.png"),
    ]


def build_panels(args, view, overlays):
    structure = load(Path(args.base) / f"structure_{view}.png")
    panels = [labeled(opaque(structure), "SCP + VCP structure")]
    for label, path in variant_paths(args, view):
        image = load(path)
        rendered = overlay(structure, image) if overlays else opaque(image)
        panels.append(labeled(rendered, f"{label} — {'overlay' if overlays else 'skin'}"))
    return panels


def main(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    for view in ("front", "threequarter", "side"):
        sheet(build_panels(args, view, False)).save(output / f"collagen_skin_{view}.png")
        sheet(build_panels(args, view, True)).save(output / f"collagen_overlay_{view}.png")


main(parse_args())

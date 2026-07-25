import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--coarse", required=True)
    parser.add_argument("--fine", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


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
    draw = ImageDraw.Draw(panel)
    draw.text((16, 9), label, fill=(235, 240, 248, 255), font=font())
    return panel


def font():
    return ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 22)


def sheet(panels):
    width, height = panels[0].size
    result = Image.new("RGBA", (width * 3, height * 2), (13, 16, 22, 255))
    for index, panel in enumerate(panels):
        result.paste(panel, ((index % 3) * width, (index // 3) * height))
    return result


def variants(args, view):
    return [
        ("Tight combined wrap", Path(args.base) / f"balanced_{view}.png"),
        ("Rest envelope 3 cm", Path(args.coarse) / f"rest_3cm_{view}.png"),
        ("Rest envelope 4 cm", Path(args.fine) / f"rest_4cm_{view}.png"),
        ("Rest envelope 5 cm", Path(args.coarse) / f"rest_5cm_{view}.png"),
        ("Rest envelope 8 cm", Path(args.coarse) / f"rest_8cm_{view}.png"),
    ]


def panels(args, view, use_overlay):
    structure = load(Path(args.base) / f"structure_{view}.png")
    result = [labeled(opaque(structure), "SCP + VCP structure")]
    for label, path in variants(args, view):
        skin = load(path)
        image = overlay(structure, skin) if use_overlay else opaque(skin)
        result.append(labeled(image, label))
    return result


def save_view(args, output, view):
    skin = sheet(panels(args, view, False))
    mixed = sheet(panels(args, view, True))
    skin.save(output / f"rest_skin_{view}.png")
    mixed.save(output / f"rest_overlay_{view}.png")


def main(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    for view in ("front", "threequarter", "side"):
        save_view(args, output, view)


if __name__ == "__main__":
    main(parse_args())

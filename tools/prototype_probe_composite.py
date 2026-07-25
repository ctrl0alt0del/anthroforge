import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def load_rgba(path):
    return Image.open(path).convert("RGBA")


def dark_background(size):
    return Image.new("RGBA", size, (13, 16, 22, 255))


def opaque_view(image):
    return Image.alpha_composite(dark_background(image.size), image)


def translucent(image, opacity):
    result = image.copy()
    alpha = result.getchannel("A").point(lambda value: int(value * opacity))
    result.putalpha(alpha)
    return result


def overlay(structure, skin):
    base = opaque_view(structure)
    return Image.alpha_composite(base, translucent(skin, 0.48))


def font(size):
    return ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", size)


def labeled(image, label):
    panel = Image.new("RGBA", (image.width, image.height + 44), (13, 16, 22, 255))
    panel.paste(image, (0, 44))
    draw = ImageDraw.Draw(panel)
    draw.text((16, 9), label, fill=(235, 240, 248, 255), font=font(22))
    return panel


def combine(panels, columns):
    width, height = panels[0].size
    rows = (len(panels) + columns - 1) // columns
    sheet = Image.new("RGBA", (width * columns, height * rows), (13, 16, 22, 255))
    for index, panel in enumerate(panels):
        sheet.paste(panel, ((index % columns) * width, (index // columns) * height))
    return sheet


def view_panels(folder, view):
    structure = load_rgba(folder / f"structure_{view}.png")
    panels = [labeled(opaque_view(structure), "SCP + VCP structure")]
    for name in ("detail", "balanced", "bridge"):
        skin = load_rgba(folder / f"{name}_{view}.png")
        panels.append(labeled(opaque_view(skin), f"{name.title()} probe — skin"))
    return panels + overlay_panels(folder, view, structure)


def overlay_panels(folder, view, structure):
    panels = [labeled(opaque_view(structure), "Structure reference")]
    for name in ("detail", "balanced", "bridge"):
        skin = load_rgba(folder / f"{name}_{view}.png")
        panels.append(labeled(overlay(structure, skin), f"{name.title()} probe — overlay"))
    return panels


def save_outputs(source, output):
    for view in ("front", "threequarter", "side"):
        panels = view_panels(source, view)
        combine(panels, 4).save(output / f"comparison_{view}.png")
        save_overlays(source, output, view)


def save_overlays(source, output, view):
    structure = load_rgba(source / f"structure_{view}.png")
    for name in ("detail", "balanced", "bridge"):
        skin = load_rgba(source / f"{name}_{view}.png")
        overlay(structure, skin).save(output / f"overlay_{name}_{view}.png")


def main(args):
    source, output = Path(args.input), Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    save_outputs(source, output)


main(parse_args())

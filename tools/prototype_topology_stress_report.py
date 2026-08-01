import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


VARIANTS = ("no_guides", "mouth_only", "eyes_only",
            "alien_forehead", "moved_mismatched")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def load_case(root, name):
    folder = Path(root, name, "renders")
    image = Image.open(folder / "front.png").convert("RGB")
    metrics = json.loads((folder / "metrics.json").read_text(encoding="utf-8"))
    return image, metrics


def failure_reasons(values):
    reasons = []
    checks = (("nonmanifold_edges", 0, "nonmanifold"),
              ("self_intersections", 0, "intersections"),
              ("degenerate_faces", 0, "degenerates"))
    reasons.extend(label for key, expected, label in checks if values[key] != expected)
    if values["edge_symmetry_error"] > 1.0e-8:
        reasons.append("edge symmetry")
    if values["aspect_p95"] > 2.0 or values["aspect_max"] > 8.0:
        reasons.append("quad aspect")
    if values["valence"]["maximum"] > 6:
        reasons.append("valence")
    if not guides_exact(values["guides"]):
        reasons.append("guide loss")
    return reasons


def guides_exact(values):
    return all(item["faces"] == item["expected_faces"] and item["vertex_error"] == 0.0
               for item in values.values())


def panel_label(name, values):
    reasons = failure_reasons(values)
    state = "PASS" if not reasons else "FAIL: " + ", ".join(reasons)
    quality = f"{values['faces']} quads | p95 {values['aspect_p95']:.2f} | max {values['aspect_max']:.2f}"
    return name.replace("_", " ").title(), state, quality


def font(size):
    return ImageFont.truetype("arial.ttf", size)


def paste_panel(canvas, case, index):
    image, values, name = case
    column, row = index % 3, index // 3
    left, top = column * 640, row * 650
    fitted = ImageOps.fit(image, (620, 560), method=Image.Resampling.LANCZOS)
    canvas.paste(fitted, (left + 10, top + 80))
    draw_panel_text(canvas, panel_label(name, values), left, top)


def draw_panel_text(canvas, labels, left, top):
    draw = ImageDraw.Draw(canvas)
    draw.text((left + 12, top + 8), labels[0], fill=(235, 242, 250), font=font(24))
    color = (95, 225, 145) if labels[1] == "PASS" else (255, 105, 95)
    draw.text((left + 12, top + 37), labels[1], fill=color, font=font(18))
    draw.text((left + 12, top + 60), labels[2], fill=(180, 194, 211), font=font(15))


def main():
    args = parse_args()
    cases = [(*load_case(args.root, name), name) for name in VARIANTS]
    canvas = Image.new("RGB", (1920, 1300), (7, 10, 16))
    for index, case in enumerate(cases):
        paste_panel(canvas, case, index)
    canvas.save(args.output)


if __name__ == "__main__":
    main()

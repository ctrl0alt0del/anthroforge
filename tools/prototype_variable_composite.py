import argparse
from pathlib import Path

from prototype_rest_composite import labeled, load, opaque, overlay, sheet


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--uniform", required=True)
    parser.add_argument("--variable", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--profile", choices=("falloff", "areas"), default="falloff")
    return parser.parse_args()


def falloff_paths(args, view):
    return [
        ("Tight combined wrap", Path(args.base) / f"balanced_{view}.png"),
        ("Uniform collagen 4 cm", Path(args.uniform) / f"rest_4cm_{view}.png"),
        ("Variable - narrow", Path(args.variable) / f"semantic_narrow_{view}.png"),
        ("Variable - balanced", Path(args.variable) / f"semantic_balanced_{view}.png"),
        ("Variable - wide", Path(args.variable) / f"semantic_wide_{view}.png"),
    ]


def area_paths(args, view):
    folder = Path(args.variable)
    return [
        ("Tight combined wrap", Path(args.base) / f"balanced_{view}.png"),
        ("Uniform collagen 4 cm", Path(args.uniform) / f"rest_4cm_{view}.png"),
        ("Zero ear + nose", folder / f"ear_nose_only_{view}.png"),
        ("Also low eyes", folder / f"plus_eyes_{view}.png"),
        ("Also low mouth", folder / f"plus_eyes_mouth_{view}.png"),
    ]


def skin_paths(args, view):
    return area_paths(args, view) if args.profile == "areas" else falloff_paths(args, view)


def comparison_panels(args, view, use_overlay):
    structure = load(Path(args.base) / f"structure_{view}.png")
    result = [labeled(opaque(structure), "SCP + VCP structure")]
    for label, path in skin_paths(args, view):
        skin = load(path)
        image = overlay(structure, skin) if use_overlay else opaque(skin)
        result.append(labeled(image, label))
    return result


def diagnostic_panels(args, view):
    result = []
    folder = Path(args.variable)
    for name, label in diagnostic_names(args):
        field = load(folder / f"{name}_field_{view}.png")
        skin = load(folder / f"{name}_{view}.png")
        result.append(labeled(opaque(field), f"{label} - collagen field"))
        result.append(labeled(opaque(skin), f"{label} - resulting skin"))
    return [result[index] for index in (0, 2, 4, 1, 3, 5)]


def diagnostic_names(args):
    if args.profile == "areas":
        return [("ear_nose_only", "Ear + nose"), ("plus_eyes", "Plus eyes"),
                ("plus_eyes_mouth", "Plus mouth")]
    return [("semantic_narrow", "Narrow"), ("semantic_balanced", "Balanced"),
            ("semantic_wide", "Wide")]


def save_view(args, output, view):
    sheet(comparison_panels(args, view, False)).save(output / f"variable_skin_{view}.png")
    sheet(comparison_panels(args, view, True)).save(output / f"variable_overlay_{view}.png")
    sheet(diagnostic_panels(args, view)).save(output / f"variable_field_{view}.png")


def main(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    for view in ("front", "threequarter", "side"):
        save_view(args, output, view)


if __name__ == "__main__":
    main(parse_args())

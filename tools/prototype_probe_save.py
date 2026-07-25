import argparse
import sys

import bpy
import numpy as np


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mesh", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--name", default="AF_PROBE_BALANCED")
    parser.add_argument("--collagen-window", type=float, default=0.0)
    parser.add_argument("--rest-offset", type=float, default=0.0)
    parser.add_argument("--collagen-profile", default="")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def create_skin(path, name):
    data = np.load(path)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(data["vertices"].tolist(), [], data["faces"].tolist())
    mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
    if "collagen" in data:
        add_collagen_attribute(mesh, data["collagen"])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def add_collagen_attribute(mesh, values):
    attribute = mesh.attributes.new("af_collagen", "FLOAT", "POINT")
    attribute.data.foreach_set("value", values)


def hide_previous_skin():
    for obj in bpy.data.objects:
        if obj.get("af_draft_skin"):
            obj.hide_viewport = obj.hide_render = True


def main(args):
    hide_previous_skin()
    skin = create_skin(args.mesh, args.name)
    skin["af_probe_prototype"] = True
    skin["af_probe_radius"] = 0.06
    skin["af_skin_offset"] = 0.015
    skin["af_collagen_window"] = args.collagen_window
    skin["af_collagen_profile"] = args.collagen_profile
    skin["af_scp_rest_offset"] = args.rest_offset
    bpy.context.view_layer.objects.active = skin
    skin.select_set(True)
    bpy.ops.wm.save_as_mainfile(filepath=args.output, copy=True)


if __name__ == "__main__":
    main(parse_args())

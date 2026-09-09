"""Render numerical skeleton trial evidence as standalone inspection figures."""
import json
import sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection


def mesh_rows(snapshot):
    for mesh in snapshot["meshes"]:
        matrix = np.array(mesh["matrix"])
        vertices = np.array(mesh["vertices"]) @ matrix[:3,:3].T + matrix[:3,3]
        yield mesh["id"], vertices, np.array(mesh["triangles"])


def draw_context(axis, meshes, axes, low, high):
    for identity, vertices, triangles in meshes:
        if np.any(vertices.max(0) < low) or np.any(vertices.min(0) > high):
            continue
        axis.add_collection(PolyCollection(vertices[triangles][:,:,axes], facecolors="#788e87", alpha=.13,
                                           edgecolors="#506962", linewidths=.15))


def draw_output(axis, output, axes):
    if "faces" in output:
        vertices, faces = np.array(output["inflated"]), np.array(output["faces"])
        axis.add_collection(PolyCollection(vertices[faces][:,:,axes], facecolors="#c57b65", alpha=.45, edgecolors="none"))
        contacts = sorted(set(i % len(faces) for i in output.get("contact",{}).get("triangles",[])))
        axis.add_collection(PolyCollection(vertices[faces[contacts]][:,:,axes], facecolors="#c31428", alpha=.85))
    for row in output.get("fibers",[output]):
        points = np.array(row["points"])
        axis.plot(points[:,axes[0]],points[:,axes[1]],color="#633927",linewidth=.6)
        for anchor in row.get("anchors",[]):
            point = anchor["point"]
            axis.scatter(point[axes[0]],point[axes[1]],s=8,c="#e3a71f",zorder=4)


def render(folder, name, output, snapshot, published=False, bounds=None):
    points = np.array(output.get("inflated",output.get("points",[])))
    if not len(points):
        return
    low, high = (points.min(0)-.3, points.max(0)+.3) if bounds is None else bounds
    fig, axs = plt.subplots(1,3,figsize=(15,6),layout="constrained")
    for axis, axes in zip(axs,((1,2),(0,2),(1,0))):
        draw_context(axis,list(mesh_rows(snapshot)),axes,low,high)
        draw_output(axis,output,axes)
        axis.set(xlim=(low[axes[0]],high[axes[0]]),ylim=(low[axes[1]],high[axes[1]]),aspect="equal",
                 xlabel="XYZ"[axes[0]]+" (scene units)",ylabel="XYZ"[axes[1]]+" (scene units)")
    fig.suptitle(name+(" — published geometry" if published else " — unpublished diagnostic preview")+"\nRed: inflated penetration; gold: SCP anchors")
    fig.savefig(folder/(name+".png"),dpi=130)
    plt.close(fig)


def measurements(output):
    if "inflated" not in output:
        return dict(anchors=len(output.get("anchors",[])))
    displacement = np.linalg.norm(np.array(output["inflated"])-output["base"],axis=1)
    return dict(fibers=len(output["fibers"]), max_displacement=float(displacement.max()),
                configured_amount=output["config"]["amount"], penetration_area=output["contact"].get("area"),
                penetration_depth=output["contact"].get("depth"), blockers=output["contact"].get("blockers"))


def main():
    folder, snapshot_path = map(Path,sys.argv[1:])
    snapshot = json.loads(snapshot_path.read_text())
    summary = {}
    for path in sorted(folder.glob("*_response.json")):
        result = json.loads(path.read_text())
        for asset in result["assets"]:
            if asset["kind"] != "geometry":
                continue
            output = json.loads(Path(asset["path"]).read_text())
            render(folder,path.stem,output,snapshot,result["published"])
            summary[path.stem] = measurements(output)
    (folder/"measurements.json").write_text(json.dumps(summary,indent=2))


if __name__ == "__main__":
    main()

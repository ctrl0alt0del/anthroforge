"""Narrow the anatomy experiment to surface-volume parts, with explicit proxy bindings."""
import json
import sys
from pathlib import Path
import numpy as np


def projection(mesh, normal):
    linear = np.array(mesh["matrix"])[:3,:3]
    ray = np.linalg.solve(linear, -np.asarray(normal))
    expected = linear.T @ normal
    return dict(direction_in_frame=(ray/np.linalg.norm(ray)).tolist(),
                expected_normal_in_frame=(expected/np.linalg.norm(expected)).tolist())


def belly(folder, meshes):
    doc = json.loads((folder / "muscle_2022_dsl.json").read_text())
    doc["document_id"] = "biceps_visible_belly"
    doc["context"]["scope"] = "Biceps visible belly volume only; humerus support proxies omit the proximal tendon. Uncalibrated experiment."
    for index, name in enumerate(doc["regions"]):
        doc["targets"][name]["binding"]["id"] = "SCP_13"
        shape = doc["regions"][name]["definition"]
        shape["seeds"] = [[.20+index*.30, y, .9] for y in (.4,.7)]
        spec = doc["regions"][name]["projection"]
        spec.update(projection(meshes["SCP_13"], [-1.,0,0]), search_distance=dict(value=.5, unit="scene"))
    doc["volume_presets"]["baseline"]["boundary"].update(along=.12, across=.12)
    doc["volume_presets"]["baseline"]["flip_normals"] = True
    doc["policies"]["default"]["refinement"].update(max_added_fibers=6, max_attempts=10)
    (folder / "muscle_belly_dsl.json").write_text(json.dumps(doc, indent=2))


def thoracic(folder):
    doc = json.loads((folder / "muscle_2005_dsl.json").read_text())
    doc["document_id"] = "thoracic_erector_volume"
    doc["context"]["scope"] = "Thoracic portion of surface column. Ribs act as support proxies; endpoints are volume boundaries, not anatomical insertions."
    keep = {"station_2", "station_3", "station_4"}
    for group in ("targets","frames","regions"):
        doc[group] = {key:value for key,value in doc[group].items() if key in keep}
    recipe = doc["recipes"]["pattern"]
    recipe["region_roles"] = {key:value for key,value in recipe["region_roles"].items() if key in keep}
    stations = [row for row in recipe["construction"]["stations"] if row["id"] in keep]
    adjust_stations(doc, stations)
    recipe["construction"]["stations"] = stations
    bindings = doc["muscles"]["example_muscle"]["region_bindings"]
    doc["muscles"]["example_muscle"]["region_bindings"] = {k:v for k,v in bindings.items() if k in keep}
    (folder / "muscle_thoracic_dsl.json").write_text(json.dumps(doc, indent=2))


def adjust_stations(doc, stations):
    for index, row in enumerate(stations):
        row.update(s=index/(len(stations)-1), role=("origin","guide","insertion")[index])
        purpose = "route_touch" if index == 1 else "attachment"
        row["offset"]["value"] = .008 if index == 1 else 0
        doc["regions"][row["id"]]["purpose"] = purpose
        doc["recipes"]["pattern"]["region_roles"][row["id"]]["purpose"] = purpose


def main():
    folder, path = map(Path, sys.argv[1:])
    meshes = {m["id"]:m for m in json.loads(path.read_text())["meshes"]}
    belly(folder, meshes)
    thoracic(folder)


if __name__ == "__main__":
    main()

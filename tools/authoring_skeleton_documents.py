"""Convert earlier designer experiments to normalized region-based test documents.

These are provisional placements, not validated anatomical templates.
"""
import json
import sys
from copy import deepcopy
from pathlib import Path
import numpy as np

ADDON = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON))
from core.authoring.model import MeshSnapshot
from core.authoring.geometry import triangles, surface_distance, normalized
from core.authoring.validation import document as validate
from core.authoring.nearest import nearest


def evidence():
    return dict(basis="inferred", sources=["reference"],
                note="Normalized from earlier designer experiment. Attachment regions and volume need anatomical review.")


def chart_point(mesh, point):
    point, index = nearest(triangles(mesh), np.asarray(point))
    point = point*.9999 + triangles(mesh)[index].mean(0)*.0001
    local = np.linalg.solve(mesh.matrix[:3,:3], np.array(point)-mesh.matrix[:3,3])
    low, high = mesh.vertices.min(0), mesh.vertices.max(0)
    return np.clip((local-low)/(high-low), 0, 1).tolist()


def direction(mesh, point):
    tris = triangles(mesh)
    candidates = np.argsort(np.linalg.norm(tris.mean(1)-point, axis=1))[:64]
    index = min(candidates, key=lambda i: surface_distance(tris[i:i+1], point))
    normal = normalized(np.cross(tris[index,1]-tris[index,0], tris[index,2]-tris[index,0]))
    return normalized(mesh.matrix[:3,:3].T @ normal).tolist()


def region(template, mesh, pins, name, purpose):
    result = deepcopy(template)
    result.update(frame=name, concept="model_support."+name, purpose=purpose, evidence=evidence())
    result["definition"] = dict(kind="curve", closed=False, seeds=[chart_point(mesh, p["point"]) for p in pins])
    result["definition"]["seeds"] = list(map(list, dict.fromkeys(map(tuple, result["definition"]["seeds"]))))
    normal = direction(mesh, pins[len(pins)//2]["point"])
    world_normal = normalized(np.linalg.solve(mesh.matrix[:3,:3].T, normal))
    ray = normalized(np.linalg.solve(mesh.matrix[:3,:3], -world_normal))
    result["projection"].update(direction_in_frame=ray.tolist(), expected_normal_in_frame=normal,
        min_normal_dot=.1, search_distance=dict(value=.05, unit="scene"), max_surface_error=dict(value=.02, unit="scene"))
    return result


def add_station(doc, templates, mesh, pins, index, count):
    name = "station_"+str(index)
    purpose = "attachment" if index in (0, count-1) else "route_touch"
    doc["targets"][name] = dict(concept="model."+mesh.id, side="right", binding=dict(kind="scene_scp_id", id=mesh.id))
    doc["frames"][name] = dict(deepcopy(templates["frame"]), owner=name, evidence=evidence())
    doc["regions"][name] = region(templates["region"], mesh, pins, name, purpose)
    recipe = doc["recipes"]["pattern"]
    recipe["region_roles"][name] = dict(anatomical_target="unverified."+name, region_kind="curve", purpose=purpose)
    recipe["construction"]["stations"].append(dict(id=name, s=index/(count-1), region_role=name,
        role="origin" if index == 0 else "insertion" if index == count-1 else "guide",
        sample=dict(kind="curve_span", start=0, end=1), offset=dict(value=0 if purpose == "attachment" else .008, unit="scene")))
    doc["muscles"]["example_muscle"]["region_bindings"][name] = dict(region=name, relationship="support_proxy",
        reason="Coarse SCP support inferred from earlier placement; exact anatomical footprint is unannotated.", evidence=evidence())


def prepare(template, item):
    doc = deepcopy(template)
    doc.update(document_id=item["id"].lower()+"_dsl", targets={}, frames={}, regions={})
    doc["sources"] = dict(reference=dict(title="Earlier skeleton route experiment", kind="designer",
        locator="local:final_routes.json", version="v3", license="User workspace reference"))
    doc["context"].update(reference_pose="rest", scope="Representative skeleton authoring evaluation", example_only=True)
    recipe = doc["recipes"]["pattern"]
    recipe.update(concept=item["name"], region_roles={}, evidence=evidence())
    recipe["construction"]["stations"] = []
    doc["muscles"]["example_muscle"].update(side="right", region_bindings={})
    doc["volume_presets"]["baseline"].update(applies_to=[item["name"]], evidence=evidence())
    return doc


def volume(doc, item):
    preset = doc["volume_presets"]["baseline"]
    amount = .81 if "Biceps" in item["name"] else .67 if "Pectoralis" in item["name"] else .38
    preset.update(amount=dict(value=amount, unit="scene"), radius=dict(fraction=.65, of="reference_fiber_length"),
                  direction_depth=dict(value=1, unit="scene"))
    preset["shape_checks"][0].update(minimum=dict(value=amount*.35, unit="scene"), maximum=dict(value=amount*1.1, unit="scene"))
    preset["boundary"].update(across=.10, along=.05)
    first, last = item["fibers"][0]["pins"], item["fibers"][-1]["pins"]
    across = np.array(last[len(last)//2]["point"])-first[len(first)//2]["point"]
    along = np.array(first[-1]["point"])-first[0]["point"]
    preset["flip_normals"] = bool(np.dot(np.cross(across,along), item["normal"]) < 0)
    doc["policies"]["default"]["solver_budget_ms"] = 30000
    doc["policies"]["default"]["refinement"].update(max_added_fibers=2, max_attempts=3)


def create(template, item, meshes):
    doc = prepare(template, item)
    templates = dict(frame=template["frames"]["origin"], region=template["regions"]["origin"])
    count = len(item["fibers"][0]["pins"])
    for index in range(count):
        pins = [f["pins"][index] for f in item["fibers"]]
        if len({p["scp"] for p in pins}) != 1:
            raise ValueError("Station crosses SCP owners; split the attachment region explicitly")
        add_station(doc, templates, meshes[pins[0]["scp"]], pins, index, count)
    volume(doc, item)
    return validate(doc)


def main():
    snapshot, routes, folder = map(Path, sys.argv[1:])
    folder.mkdir(parents=True, exist_ok=True)
    meshes = {m["id"]: MeshSnapshot(m["id"], np.array(m["vertices"]), np.array(m["triangles"]), np.array(m["matrix"]))
              for m in json.loads(snapshot.read_text())["meshes"]}
    template = json.loads((ADDON / "tests/fixtures/authoring/02-upper-arm.json").read_text())
    for item in json.loads(routes.read_text()):
        if item["id"] in ("MUSCLE_2005", "MUSCLE_2011", "MUSCLE_2022"):
            doc = create(template, item, meshes)
            (folder / (doc["document_id"]+".json")).write_text(json.dumps(doc, indent=2))


if __name__ == "__main__":
    main()

"""Eight independent small attachment supports for closed-loft integration."""
import json
from copy import deepcopy
from pathlib import Path
import bpy
from _helpers import scp_with_object


def fixture(root):
    doc = json.loads((Path(__file__).parents[1]/"fixtures/authoring/04-oral-ring.json").read_text())
    frame = next(iter(doc["frames"].values()))
    doc.update(targets={},frames={})
    doc["context"]["reference_pose"] = "rest"
    for name, region in doc["regions"].items():
        attach(root,doc,name,region,frame)
    doc["volume_presets"]["baseline"]["flip_normals"] = True
    return doc


def attach(root, doc, name, region, frame):
    radius = 1 if name.startswith("inner") else 2
    x,z = dict(upper=(0,1),left=(-1,0),lower=(0,-1),right=(1,0))[name.split("_")[-1]]
    bpy.ops.mesh.primitive_cube_add(size=.02, location=(x*radius,0,z*radius))
    scp = scp_with_object(root,name,bpy.context.object)
    doc["targets"][name] = dict(concept="demo."+name,side="midline",binding=dict(kind="scene_scp_id",id=scp.id))
    doc["frames"][name] = dict(deepcopy(frame),owner=name)
    region.update(frame=name,definition=dict(kind="point",seed=[.5,1,.5]))
    region["projection"].update(search_distance=dict(value=.05,unit="scene"),max_surface_error=dict(value=.001,unit="scene"))

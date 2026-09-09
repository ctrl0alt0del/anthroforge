"""Build pinned 0.3 schemas from the unchanged 0.2 compatibility schemas."""
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]/"core/authoring/schemas"
REF = lambda name: {"$ref": "#/$defs/"+name}
NUMBER = dict(type="number",minimum=0,maximum=1)
INTEGER = dict(type="integer",minimum=1)


def obj(properties, required=None):
    return dict(type="object",properties=properties,required=list(properties) if required is None else required,additionalProperties=False)


def array(items, minimum=1, maximum=4096):
    return dict(type="array",items=items,minItems=minimum,maxItems=maximum)


def definitions(defs):
    defs["conformance"] = obj(dict(stations=array(REF("id")),max_error=REF("length"),
        blend_span=dict(type="number",exclusiveMinimum=0,maximum=.5),max_samples=dict(INTEGER,maximum=513)))
    defs["open_loft"]["properties"]["boundary_conformance"] = REF("conformance")
    defs["shape_check"]["properties"]["metric"]["enum"] += ["section_width","section_arc_length"]
    defs["projection"]["properties"]["hit_policy"]["enum"].append("closest_seed")
    defs["projection"]["properties"]["selection_margin"] = REF("length")
    chart = obj(dict(domain=array(array(NUMBER,2,2),1,2),direction_in_frame=REF("xyz"),expected_normal_in_frame=REF("xyz")))
    defs["projection"]["properties"]["charts"] = array(chart,1,32)
    defs["policy"]["properties"]["max_surface_vertices"] = dict(INTEGER,maximum=1000000)
    defs["policy"]["properties"]["total_budget_ms"] = dict(INTEGER,maximum=3600000)
    landmark_frame(defs)


def landmark_frame(defs):
    standard = deepcopy(defs["frame"])
    landmark = deepcopy(standard)
    landmark["properties"]["kind"] = {"enum":["landmark_box"]}
    del landmark["properties"]["axes_owner_local"]
    landmark["required"].remove("axes_owner_local")
    landmark["properties"]["landmarks_q"] = obj(dict(origin=REF("q3"),x=REF("q3"),xy=REF("q3")))
    landmark["required"].append("landmarks_q")
    defs["frame"] = {"oneOf":[standard,landmark]}


def protocol(schema):
    definitions(schema["$defs"])
    variants = schema["$defs"]["request"]["oneOf"]
    templates = {row["properties"]["op"]["enum"][0]:row for row in variants}
    for name in ("inspect","export"):
        templates[name]["properties"]["params"]["properties"]["source"] = {"enum":["published","draft"]}
    for name, source in (("draft","build"),("patch_draft","patch"),("publish_draft","export")):
        row = deepcopy(templates[source]); row["properties"]["op"] = {"enum":[name]}
        row["properties"]["params"] = draft_params(name)
        variants.append(row)
    schema["$defs"]["response"]["properties"]["op"]["enum"] += ["draft","patch_draft","publish_draft"]
    schema["$defs"]["response"]["properties"]["draft_revision"] = dict(type="integer",minimum=0)
    schema["$defs"]["capabilities"]["properties"]["operations"]["items"]["enum"] += ["draft","patch_draft","publish_draft"]
    schema["$defs"]["diagnostic"]["properties"]["document_pointer"]["minLength"] = 0


def draft_params(name):
    values = dict(scene_id=REF("id"),expected_scene_revision=dict(type="string",minLength=1),
                  expected_draft_revision=dict(type="integer",minimum=0))
    if name == "draft":
        values["document"] = REF("document")
    else:
        values["document_id"] = REF("id")
    if name == "patch_draft":
        values["operations"] = array(REF("patch_item"))
    return obj(values)


def main():
    for name in ("authoring","protocol"):
        schema = json.loads((ROOT/(name+".schema.json")).read_text().replace("0.2.0","0.3.0"))
        protocol(schema) if name == "protocol" else definitions(schema["$defs"])
        (ROOT/(name+"-0.3.schema.json")).write_text(json.dumps(schema,indent=2)+"\n",encoding="utf-8")


if __name__ == "__main__":
    main()

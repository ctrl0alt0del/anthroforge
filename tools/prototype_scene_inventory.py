import json

import bpy


def object_record(obj):
    data = obj.data if obj.type == "MESH" else None
    return {
        "name": obj.name,
        "type": obj.type,
        "parent": obj.parent.name if obj.parent else None,
        "vertices": len(data.vertices) if data else 0,
        "faces": len(data.polygons) if data else 0,
        "hidden": obj.hide_get(),
        "props": {key: str(obj[key])[:200] for key in obj.keys()},
    }


records = [object_record(obj) for obj in bpy.data.objects]
print("AF_INVENTORY_BEGIN")
print(json.dumps(records, indent=2))
print("AF_INVENTORY_END")

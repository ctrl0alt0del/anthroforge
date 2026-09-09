"""RNA mementos exclude transient runtime status."""
from ...core.importing.rna import scalar_dict, apply_scalar_dict


def record(item):
    values = scalar_dict(item)
    collections = {p.identifier: [record(x) for x in getattr(item, p.identifier)]
                   for p in item.bl_rna.properties if p.type == "COLLECTION"}
    custom = {k: plain(item[k]) for k in item.keys() if k.startswith("af_authoring")}
    return dict(values=values, collections=collections, custom=custom)


def plain(value):
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "to_list"):
        return value.to_list()
    return value


def restore(item, value):
    apply_scalar_dict(item, value["values"])
    for name, rows in value["collections"].items():
        collection = getattr(item, name)
        collection.clear()
        for row in rows:
            restore(collection.add(), row)
    for key in list(item.keys()):
        if key.startswith("af_authoring"):
            del item[key]
    for key, data in value["custom"].items():
        item[key] = data

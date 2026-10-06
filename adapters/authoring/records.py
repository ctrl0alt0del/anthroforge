"""RNA mementos exclude transient runtime status."""
from ...core.importing.rna import scalar_dict, apply_scalar_dict
from ...core.vcp.muscle_section_profile import PROFILE_FIELDS


def record(item):
    values = _record_values(item)
    collections = {p.identifier: [record(x) for x in getattr(item, p.identifier)]
                   for p in item.bl_rna.properties if p.type == "COLLECTION"}
    custom = {k: plain(item[k]) for k in item.keys() if k.startswith("af_authoring")}
    result = dict(values=values, collections=collections, custom=custom)
    if hasattr(item, "settings") and item.bl_rna.identifier == "AF_BranchConnection_Property":
        result["pointers"] = {"settings": record(item.settings)}
    return result


def _record_values(item):
    skip = [p.identifier for p in item.bl_rna.properties if p.identifier.startswith('proxy_')]
    values = scalar_dict(item, skip if item.bl_rna.identifier == 'AF_DataShortcut_Property' else ())
    if _default_profile(item, values):
        values = {key: value for key, value in values.items() if key not in PROFILE_FIELDS}
    if values.get('output_domain_mode') == 'FULL':
        from ...core.vcp.muscle_output_domain import FIELDS
        values = {key: value for key, value in values.items() if key not in FIELDS}
    return _envelope_record(item, _legacy_fiber_values(values))


def _legacy_fiber_values(values):
    from ...core.vcp.free_path import FREE_FIELDS
    defaults = ('CONTROLLED', '', 0, 64)
    if all(values.get(key, default) == default for key, default in zip(FREE_FIELDS, defaults)):
        return {key: value for key, value in values.items() if key not in FREE_FIELDS}
    return values


def _default_profile(item, values):
    if values.get('section_profile_version') != 0 or values.get('inflation_mode') == 'SECTION_PROFILE':
        return False
    for key in PROFILE_FIELDS:
        prop = item.bl_rna.properties[key]
        default = list(prop.default_array) if getattr(prop, 'is_array', False) else prop.default
        if values[key] != default:
            return False
    return True


def plain(value):
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "to_list"):
        return value.to_list()
    return value


def restore(item, value):
    apply_scalar_dict(item, value["values"])
    for name, row in value.get("pointers", {}).items():
        restore(getattr(item, name), row)
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


def _envelope_record(item, values):
    values.pop('envelope_edit_side', None)
    if values.get('envelope_version', 0) == 0:
        return {k: v for k, v in values.items() if not k.startswith('envelope_') and k != 'inflation_secondary'}
    if item.bl_rna.identifier == 'AF_MuscleVCP_Property' and item in item.id_data.af_vcp_system.muscles[:]:
        from ...core.authoring.envelope_config import configuration
        values['envelope_configuration'] = configuration(item.id_data, item)
    return values

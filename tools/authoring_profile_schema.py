"""Strict Section Profile vocabulary for native operations and authored shapes."""
from copy import deepcopy


def obj(fields, required=None):
    return dict(type="object", properties=fields, required=list(fields) if required is None else required, additionalProperties=False)


def vector(item):
    return dict(type="array", items=item, minItems=4, maxItems=4)


def configuration(depth):
    return obj(dict(mode=dict(enum=["section_profile"]), profile_version=dict(type="integer", enum=[1]),
        enabled=dict(type="boolean"), flip_normals=dict(type="boolean"), depths=vector(depth),
        peaks=vector(dict(type="number", minimum=.1, maximum=.9)), roundness=dict(type="number", minimum=.25, maximum=4),
        direction=dict(enum=["local", "smooth", "section"])))


def native_definition(defs, prefix=""):
    profile = configuration({"$ref": "#/$defs/" + prefix + "length"})
    original = defs[prefix + "distributed"]["properties"]
    for key in ("applies_to", "calibration", "shape_checks", "evidence"):
        profile["properties"][key] = deepcopy(original[key])
        profile["required"].append(key)
    defs[prefix + "section_profile"] = profile
    reference = {"$ref": "#/$defs/" + prefix + "section_profile"}
    choices = defs[prefix + "volume"]["oneOf"]
    if reference not in choices:
        choices.append(reference)


def operations(defs):
    text = dict(type="string", minLength=1)
    depth = obj(dict(value=dict(type="number", minimum=0, maximum=10), unit=dict(enum=["scene"])))
    defs["profile_configuration"] = dict(oneOf=[configuration(depth), obj(dict(mode=dict(enum=["control_point", "distributed"])))])
    defs["profile_target"] = dict(oneOf=[obj({key: text}) for key in ("muscle_id", "fiber_surface_id")])
    target, config = {"$ref": "#/$defs/profile_target"}, {"$ref": "#/$defs/profile_configuration"}
    guards = dict(expected_scene_revision=text, expected_base_revision=text)
    preview = dict(target=target, configuration=config, include_geometry=dict(type="boolean"), **guards)
    create = dict(surface_id=text, name=text, initial_configuration=configuration(depth), **guards)
    return [_operation("profile_inspect", dict(target=target), ["target"]),
        _operation("profile_preview", preview, ["target", "configuration", *guards]),
        _operation("profile_configure", dict(muscle_id=text, configuration=config, **guards), ["muscle_id", "configuration", *guards]),
        _operation("create_from_surface", create, ["surface_id", *guards])]


def _operation(name, params, required):
    text = dict(type="string", minLength=1)
    return obj(dict(dsl=dict(enum=["anthroforge.authoring.protocol"]), version=dict(enum=["0.4.0"]),
        message_type=dict(enum=["request"]), request_id=text, op=dict(enum=["muscles." + name]),
        params=obj(dict(scene_id=text, **params), ["scene_id", *required])))

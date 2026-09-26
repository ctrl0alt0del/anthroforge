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


def legacy_configuration():
    ranges = dict(inflation_max_value=(0., 10.), inflation_falloff_radius=(.001, 100.),
        inflation_direction_depth=(.0001, 10.), inflation_boundary_strength=(0., 1.),
        inflation_boundary_band=(.1, 16.), inflation_boundary_power=(.1, 8.), inflation_length_taper_band=(.01, .49))
    fields = {key: dict(type="number", minimum=low, maximum=high) for key, (low, high) in ranges.items()}
    fields.update(inflation_enabled=dict(type="boolean"), inflation_falloff_type=dict(enum=["GAUSSIAN", "LINEAR", "SMOOTHSTEP"]),
        inflation_ctrl_world=dict(type="array", items=dict(type="number"), minItems=3, maxItems=3), flip_normals=dict(type="boolean"))
    native = dict(type="object", properties=fields, additionalProperties=False)
    return obj(dict(mode=dict(enum=["control_point", "distributed"]), native=native,
                    surface_flip_normals=dict(type="boolean")), ["mode", "native"])


def operations(defs):
    text = dict(type="string", minLength=1)
    depth = obj(dict(value=dict(type="number", minimum=0, maximum=10), unit=dict(enum=["scene"])))
    defs["profile_configuration"] = dict(oneOf=[configuration(depth), obj(dict(mode=dict(enum=["control_point", "distributed"]))), legacy_configuration()])
    defs["profile_target"] = dict(oneOf=[obj({key: text}) for key in ("muscle_id", "fiber_surface_id")])
    target, config = {"$ref": "#/$defs/profile_target"}, {"$ref": "#/$defs/profile_configuration"}
    guards = dict(expected_scene_revision=text, expected_base_revision=text)
    preview = dict(target=target, configuration=config, include_geometry=dict(type="boolean"), **guards)
    create = dict(surface_id=text, name=text, initial_configuration=configuration(depth), initial_envelope={'$ref': '#/$defs/native_muscle_envelope'}, **guards)
    return [_operation("profile_inspect", dict(target=target), ["target"]),
        _operation("profile_preview", preview, ["target", "configuration", *guards]),
        _operation("profile_configure", dict(muscle_id=text, configuration=config, **guards), ["muscle_id", "configuration", *guards]),
        _operation("create_from_surface", create, ["surface_id", *guards])]


def _operation(name, params, required):
    text = dict(type="string", minLength=1)
    return obj(dict(dsl=dict(enum=["anthroforge.authoring.protocol"]), version=dict(enum=["0.4.0"]),
        message_type=dict(enum=["request"]), request_id=text, op=dict(enum=["muscles." + name]),
        params=obj(dict(scene_id=text, **params), ["scene_id", *required])))

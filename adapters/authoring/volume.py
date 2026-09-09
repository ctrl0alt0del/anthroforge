"""Map resolved DSL volume to editable native inflation controls."""
import numpy as np
from ...core.authoring.codec import encode
from ...core.authoring.inflation import sample
from ...core.authoring.errors import require
from ...core.vcp.runtime_state import set_muscle_inflation_ctrl_world


def configure(muscle, output):
    config = output["config"]
    muscle.inflation_enabled = config["enabled"]
    muscle.inflation_mode = "CTRL_POINT" if config["mode"] == "control_point" else "DISTRIBUTED"
    assign_checked(muscle, "inflation_max_value", config["amount"])
    muscle.flip_normals = config["flip_normals"]
    muscle.inflation_boundary_strength = config["boundary"]["strength"]
    muscle.inflation_boundary_power = config["boundary"]["power"]
    muscle.inflation_material_along, muscle.inflation_material_across = config["boundary"]["along"], config["boundary"]["across"]
    muscle["af_authoring_material"] = encode(dict(u=output["u"], s=output["s"], config=config,
                                                   closed=output["fibers"][0]["closed"]))
    if config["mode"] == "control_point":
        configure_control(muscle, output)
    elif config["length_taper"]:
        assign_checked(muscle, "inflation_length_taper_band", config["length_taper"])


def configure_control(muscle, output):
    config = output["config"]
    muscle.inflation_falloff_type = config["falloff"].upper()
    assign_checked(muscle, "inflation_falloff_radius", config["radius"])
    assign_checked(muscle, "inflation_direction_depth", config["direction_depth"])
    base = np.array(output["base"]).reshape(len(output["u"]), len(output["s"]), 3)
    point = sample(base, output["u"], output["s"], *config["control"], output["fibers"][0]["closed"])
    set_muscle_inflation_ctrl_world(muscle, tuple(point))


def assign_checked(item, key, value):
    setattr(item, key, value)
    require(abs(getattr(item, key)-value) <= max(1e-7, abs(value)*1e-6), "NATIVE_PARAMETER_RANGE", key)

"""Scalar contributor settings are preserved by native record serialization."""
import bpy


def gap_properties():
    return {
        "skin_gap_mode": bpy.props.EnumProperty(name="Gap Settings", default="INHERIT", items=(
            ("INHERIT", "Inherit Model", "Use the model's gap filling settings"),
            ("OVERRIDE", "Override", "Use these limits for this contributor and its mirror"))),
        "skin_gap_limit_percent": bpy.props.FloatProperty(name="Maximum Gap to Close", default=0.5,
            min=0.0, max=100.0, precision=4, description="Percent of model longest axis; zero disables bridging"),
        "skin_gap_strength_percent": bpy.props.FloatProperty(name="Gap Filling Strength", default=100.0,
            min=0.0, max=100.0, precision=1, description="Amount of permitted filling; cannot override the gap limit"),
    }


def with_gap_controls(cls):
    cls.__annotations__.update(gap_properties())
    return cls

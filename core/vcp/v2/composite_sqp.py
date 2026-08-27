"""Isolated composite-step and SOC helpers for Fiber SQP ablations."""

from .trust_sqp import second_order_correction, solve_composite_sqp


COMPOSITE_SQP_VARIANTS = ("BASE", "TANGENTIAL", "COMPOSITE", "COMPOSITE_SOC")


def normalize_composite_variant(value):
    name = str(value or "BASE").upper()
    return name if name in COMPOSITE_SQP_VARIANTS else "BASE"


__all__ = ("COMPOSITE_SQP_VARIANTS", "normalize_composite_variant",
           "second_order_correction", "solve_composite_sqp")

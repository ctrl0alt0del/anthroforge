"""Analytic owned inputs for the complete native pipeline."""
from dataclasses import replace
import numpy as np
from pair_fixture_adapter import domain, wait
from core.muscle_stacking.model import material, StackingSettings
from core.muscle_stacking.native import NativeStackEngine
from core.muscle_pairs.model import DetectionSettings


def payload(side, pins=()):
    d = domain(replace(side, displacement=.5)); indices = np.arange(len(d.base))[:, None]
    m = material(d.base, d.faces, indices, np.ones(indices.shape), pins)
    return replace(d, material=m, output_indices=indices[:, 0])


def solve(sides, settings=None):
    with NativeStackEngine() as engine:
        engine.submit(sides, settings or DetectionSettings(stacking=StackingSettings()), 1)
        result = wait(engine); surfaces = engine.surfaces()
        return result, {key.muscle: value for key, value in surfaces.items()}

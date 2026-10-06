"""Capture exact scalar material interpolation; crop borders create no pins."""
import ctypes as C
from dataclasses import replace
import numpy as np
from ..muscle_pairs import abi
from .model import material


def boundary_pins(faces, count):
    faces = np.ascontiguousarray(faces, dtype=np.int64)
    flags = np.zeros(count, dtype=np.int64); call = abi.library().af_stack_boundary_pins
    call.argtypes, call.restype = [abi.IP, C.c_int, C.c_int, abi.IP], C.c_int
    if call(abi.pointer(faces), len(faces), count, abi.pointer(flags)): raise ValueError('STACK_PIN_CAPTURE_FAILED')
    return np.flatnonzero(flags)


def attach(domain, reference, result, selected):
    from ..muscle_pairs.field import triangles
    vertices, faces, _ = reference
    faces, _, _ = triangles(faces, np.zeros(len(faces), dtype=np.int64), np.arange(len(faces)))
    indices = result.material_indices
    weights = result.material_weights
    if indices is None:
        indices = np.arange(len(result.base_vertices), dtype=np.int64)[:, None]; weights = np.ones(indices.shape)
    payload = material(vertices, faces, indices[selected], weights[selected], boundary_pins(faces, len(vertices)))
    return replace(domain, material=payload, output_indices=np.array(selected, dtype=np.int64))


def transformed(value, matrix):
    points = value.vertices @ matrix[:3, :3].T + matrix[:3, 3]
    return material(points, value.faces, value.interpolation, value.weights, value.fixed)

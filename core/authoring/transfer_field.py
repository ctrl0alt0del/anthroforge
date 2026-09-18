"""One normalized cubic RBF map for every mesh; no muscle-specific rules."""
from dataclasses import dataclass
import numpy as np
from .errors import require


@dataclass(frozen=True)
class TransferField:
    centers: np.ndarray
    weights: np.ndarray
    affine: np.ndarray
    source_origin: np.ndarray
    source_scale: float
    target_origin: np.ndarray
    target_scale: float
    condition: float


def points(value):
    array = np.asarray(value, dtype=np.float64)
    require(array.ndim == 2 and array.shape[1] == 3 and len(array) > 0, 'TRANSFER_POINTS_INVALID')
    require(np.isfinite(array).all(), 'TRANSFER_POINTS_INVALID')
    return array


def normalize(value):
    origin = value.mean(axis=0)
    scale = float(np.linalg.norm(value-origin, axis=1).max())
    require(scale > np.finfo(float).eps * max(1., np.abs(origin).max()) * 32, 'TRANSFER_LANDMARKS_DEGENERATE')
    return (value-origin)/scale, origin, scale


def distances(first, second):
    return np.linalg.norm(first[:, None, :]-second[None, :, :], axis=2)


def system(centers, smoothing):
    polynomial = np.column_stack((np.ones(len(centers)), centers))
    require(np.linalg.matrix_rank(polynomial, tol=1e-9) == 4, 'TRANSFER_LANDMARKS_COPLANAR')
    separation = distances(centers, centers)
    require(np.min(separation + np.eye(len(centers))) > 1e-9, 'TRANSFER_LANDMARKS_DUPLICATED')
    kernel = separation**3 + np.eye(len(centers))*smoothing
    return np.block([[kernel, polynomial], [polynomial.T, np.zeros((4, 4))]])


def fit(source, target, smoothing=0.):
    source, target = points(source), points(target)
    require(source.shape == target.shape and 4 <= len(source) <= 256, 'TRANSFER_LANDMARK_COUNT')
    require(np.isfinite(smoothing) and smoothing >= 0, 'TRANSFER_SMOOTHING_INVALID')
    x, origin, scale = normalize(source)
    y, target_origin, target_scale = normalize(target)
    matrix = system(x, smoothing)
    condition = float(np.linalg.cond(matrix))
    require(np.isfinite(condition) and condition < 1e13, 'TRANSFER_SYSTEM_ILL_CONDITIONED')
    solution = np.linalg.solve(matrix, np.vstack((y, np.zeros((4, 3)))))
    return TransferField(x, solution[:-4], solution[-4:], origin, scale, target_origin, target_scale, condition)


def evaluate(field, value, chunk_size=1024):
    rows = points(value)
    return np.vstack([evaluate_chunk(field, rows[i:i+chunk_size]) for i in range(0, len(rows), chunk_size)])


def evaluate_chunk(field, rows):
    x = (rows-field.source_origin)/field.source_scale
    polynomial = np.column_stack((np.ones(len(x)), x))
    y = distances(x, field.centers)**3 @ field.weights + polynomial @ field.affine
    return y*field.target_scale + field.target_origin


def jacobians(field, value, chunk_size=512):
    rows = points(value)
    return np.concatenate([jacobian_chunk(field, rows[i:i+chunk_size]) for i in range(0, len(rows), chunk_size)])


def jacobian_chunk(field, rows):
    x = (rows-field.source_origin)/field.source_scale
    delta = x[:, None, :]-field.centers[None, :, :]
    gradient = 3*np.linalg.norm(delta, axis=2)[:, :, None]*delta
    jacobian = np.einsum('nkd,ko->nod', gradient, field.weights) + field.affine[1:].T
    return jacobian*(field.target_scale/field.source_scale)


def serialize(field):
    return {key: value.tolist() if isinstance(value, np.ndarray) else value for key, value in vars(field).items()}


def deserialize(value):
    arrays = {'centers', 'weights', 'affine', 'source_origin', 'target_origin'}
    return TransferField(**{key: np.asarray(item, dtype=float) if key in arrays else item for key, item in value.items()})

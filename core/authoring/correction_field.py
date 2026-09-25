"""Localized, constrained displacement fields; no Blender or optional packages."""
import numpy as np
from .errors import require


def farthest(points, count):
    chosen = [0]; distances = np.full(len(points), np.inf)
    for _ in range(min(count, len(points))-1):
        distances = np.minimum(distances, np.linalg.norm(points-points[chosen[-1]], axis=1))
        if distances.max() < 1e-12:
            break
        chosen.append(int(np.argmax(distances)))
    return points[chosen]


def separation(points, fixed):
    result = np.full(len(points), np.inf)
    for chunk in range(0, len(fixed), 128):
        delta = points[:, None]-fixed[None, chunk:chunk+128]
        result = np.minimum(result, np.linalg.norm(delta, axis=2).min(axis=1))
    return result


def smoothstep(value):
    value = np.clip(value, 0., 1.)
    return value*value*(3.-2.*value)


def basis(vertices, centers, radius, fixed, blend, influences):
    delta = np.linalg.norm(vertices[:, None]-centers, axis=2)
    weights = np.exp(-(delta/radius)**2)
    if len(fixed):
        weights *= smoothstep(separation(vertices, vertices[fixed])/blend)[:, None]
    if influences:
        envelopes = [1-smoothstep(np.linalg.norm(vertices-r['center'], axis=1)/r['radius']) for r in influences]
        weights *= np.max(envelopes, axis=0)[:, None]
    return weights


def constraints(phi, vertices, contacts):
    if not contacts:
        return np.zeros((len(phi[0]), 3)), np.eye(len(phi[0]))
    a = np.array([np.asarray(c['weights']) @ phi[c['indices']] for c in contacts])
    b = np.array([c['target']-np.asarray(c['weights']) @ vertices[c['indices']] for c in contacts])
    part = np.linalg.lstsq(a, b, rcond=1e-10)[0]
    require(np.max(np.linalg.norm(a @ part-b, axis=1)) <= 1e-7, 'CORRECTION_CONSTRAINT_CONFLICT')
    _u, s, vh = np.linalg.svd(a, full_matrices=True)
    rank = int(np.sum(s > max(s.max(initial=0)*1e-10, 1e-12)))
    return part, vh[rank:].T


def edges(faces):
    return np.unique(np.sort(faces[:, [[0, 1], [1, 2], [2, 0]]].reshape(-1, 2), axis=1), axis=0)


def build(vertices, faces, settings, fixed, contacts, seeds):
    seeds = np.vstack((seeds, [c['target'] for c in contacts])) if contacts else seeds
    require(len(seeds) > 0, 'CORRECTION_NO_INFLUENCE')
    centers = farthest(seeds, settings.get('centers', 16)); radius = settings['influence_radius']
    phi = basis(vertices, centers, radius, fixed, settings.get('protection_blend', radius*.3), settings.get('influences', []))
    part, null = constraints(phi, vertices, contacts); edge = edges(faces)
    return dict(phi=phi, part=part, null=null, centers=centers, edges=edge,
                sample_basis=np.vstack((phi, phi[faces].mean(axis=1))),
                samples=np.vstack((vertices, vertices[faces].mean(axis=1))))

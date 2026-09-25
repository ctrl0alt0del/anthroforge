"""Retain an existing native branch root while repairing its neighboring borders."""
import numpy as np
from .errors import require
from .base_partition import native_mesh
from ..vcp.branched_surface import BranchInput, prepare_assembly, assemble


def connection(before, result, spec):
    if not spec: return None
    conform(result, spec)
    main = spec['main']; child = 1-main; side = 0 if spec['side'] == 0 else -1
    old = np.asarray(before[main][side]); new = np.asarray(result['paths'][main][side])
    ids = spec['root_indices']; require(len(ids) == len(before[child]) and all(0 < i < len(old)-1 for i in ids), 'PARTITION_INVALID_ROOTS')
    require(all(a < b for a, b in zip(ids, ids[1:])), 'PARTITION_INVALID_ROOTS')
    roots = [int(np.argmin(np.linalg.norm(new-old[i], axis=1))) for i in ids]
    require(np.max(np.linalg.norm(new[roots]-old[ids], axis=1)) < 1e-7, 'PARTITION_LOCKED_JUNCTION')
    starts = np.asarray(before[child])[:, 0]
    require(np.max(np.linalg.norm(starts-old[ids], axis=1)) < 1e-7, 'PARTITION_INVALID_ROOTS')
    for j, i in zip(roots, ids): result['paths'][main][side][j] = before[main][side][i]
    return dict(main=main, side=spec['side'], root_indices=roots)


def conform(result, spec):
    main, child = spec['main'], 1-spec['main']; side = 0 if spec['side'] == 0 else -1
    paths, ts = result['paths'], result['stations']; x = np.asarray(paths[main][side])
    # Branch evaluation adds 17 stations. Insert their contact points on the parent too.
    child_row = np.asarray(paths[child][0]); extra = np.linspace(0, 1, 17)
    samples = np.column_stack([np.interp(extra, ts[child][0], child_row[:, k]) for k in range(3)])
    candidates = contact_stations(x, ts[main][side], samples)
    old = np.asarray(ts[main][0]); target = np.sort(np.r_[old, candidates])
    target = target[np.r_[True, np.diff(target) > 1e-9]]
    for i, row in enumerate(paths[main]):
        paths[main][i] = np.column_stack([np.interp(target, ts[main][i], np.asarray(row)[:, k]) for k in range(3)]).tolist()
    ts[main] = [target.tolist() for _ in paths[main]]


def contact_stations(path, stations, points):
    start, delta = path[:-1], np.diff(path, axis=0); denom = np.sum(delta*delta, axis=1); result = []
    for p in points:
        u = np.clip(np.sum((p-start)*delta, axis=1)/np.maximum(denom, 1e-24), 0, 1)
        distance = np.linalg.norm(start+u[:, None]*delta-p, axis=1); i = int(np.argmin(distance))
        if distance[i] > 1e-7: continue
        t = stations[i]+u[i]*(stations[i+1]-stations[i])
        if np.min(np.abs(np.asarray(stations)-t)) > 1e-9: result.append(t)
    return result


def meshes(result):
    spec = result.get('connection'); paths, stations = result['paths'], result['stations']
    if not spec: return [native_mesh(p, s) for p, s in zip(paths, stations)]
    main = spec['main']; child = 1-main
    branch = BranchInput('partition-child', 0 if spec['side'] == 0 else -1, tuple(spec['root_indices']),
        tuple(paths[child]), stations=tuple(stations[child]))
    assembly = prepare_assembly(paths[main], [branch], main_stations=stations[main])
    vertices, quads = assemble(assembly); quads = np.asarray(quads)
    faces = np.concatenate((quads[:, [0, 1, 2]], quads[:, [0, 2, 3]]))
    return [dict(vertices=np.asarray(vertices).tolist(), triangles=faces.tolist())]

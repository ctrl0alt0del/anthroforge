"""Independent dense body samples with the declared construction extensions."""
import numpy as np
from .smooth_native import evaluate, faces


def expected_mesh(part):
    if 'partition' in part: return partition_mesh(part)
    controls = np.asarray(part['controls']); rows = []
    body_stations = np.linspace(0, 1, 97)
    for index, fiber in enumerate(part['fibers']):
        path = np.asarray(fiber['path']); stations = np.asarray(fiber['stations'])
        body = evaluate(controls, np.c_[np.full(97, index/(len(part['fibers'])-1)), body_stations], linear=True)
        rows.append((np.r_[stations[stations < 0], body_stations, stations[stations > 1]],
                     np.vstack((path[stations < 0], body, path[stations > 1]))))
    common = np.unique(np.concatenate([row[0] for row in rows]))
    vertices = np.asarray([np.column_stack([np.interp(common, t, p[:, k]) for k in range(3)]) for t, p in rows])
    return vertices.reshape(-1, 3), faces(len(rows), len(common))


def partition_mesh(part):
    fibers = part['fibers']; common = np.unique(np.concatenate([np.linspace(0, 1, 97), *[f['stations'] for f in fibers]]))
    rows = [np.column_stack([np.interp(common, f['stations'], np.asarray(f['path'])[:, k]) for k in range(3)]) for f in fibers]
    return np.asarray(rows).reshape(-1, 3), faces(len(rows), len(common))

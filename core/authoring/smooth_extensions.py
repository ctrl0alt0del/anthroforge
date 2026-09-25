"""Fixed cubic construction extensions; independent of belly fitting controls."""
import numpy as np


def prefix(start, points):
    chord = points[0]-start; length = np.linalg.norm(chord)
    if length <= 1e-8: return points[:0]
    tangent = points[1]-points[0]; tangent *= length/max(np.linalg.norm(tangent), 1e-12)
    t = np.linspace(0, 1, 9)[:-1, None]
    return (2*t**3-3*t*t+1)*start+(t**3-2*t*t+t)*chord+(-2*t**3+3*t*t)*points[0]+(t**3-t*t)*tangent


def attach(points, hits):
    stations = np.linspace(0, 1, len(points))
    if hits[0]['mode'] == 'extend':
        extension = prefix(np.asarray(hits[0]['point']), points)
        stations = np.r_[np.linspace(-1, 0, len(extension)+1)[:-1], stations]; points = np.vstack((extension, points))
    else: points[0] = hits[0]['point']
    if hits[1]['mode'] == 'extend':
        extension = prefix(np.asarray(hits[1]['point']), points[::-1])[::-1]
        stations = np.r_[stations, np.linspace(1, 2, len(extension)+1)[1:]]; points = np.vstack((points, extension))
    else: points[-1] = hits[1]['point']
    return points, stations

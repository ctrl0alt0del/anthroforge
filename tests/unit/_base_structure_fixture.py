"""Two supplied heads joining one common belly, with intentional missing samples."""
import numpy as np


def quad(vertices, faces, corners, hole):
    start = len(vertices); rows, columns = 9, 7; a, b, c, d = np.asarray(corners)
    for t in np.linspace(0, 1, rows):
        for s in np.linspace(0, 1, columns):
            vertices.append(((1-t)*((1-s)*a+s*b)+t*((1-s)*d+s*c)).tolist())
    selected = []
    for j in range(rows-1):
        for i in range(columns-1):
            if hole and 2 <= i <= 3 and 3 <= j <= 4:
                continue
            x = start+j*columns+i; selected.extend((len(faces), len(faces)+1)); faces.extend(((x, x+1, x+columns+1), (x, x+columns+1, x+columns)))
    return selected


def arc(identity, a, b, role, segments=10):
    return dict(id=identity, vertex_ids=[a, b], role=role, segments=segments)


def border(*names):
    return [dict(arc=name.lstrip('-'), reverse=name.startswith('-')) for name in names]


def example():
    vertices = [[-.6, 0, 0], [.6, 0, 0], [.6, 2, 0], [0, 2, 0], [-.6, 2, 0], [-.4, 4, 0], [-1.4, 4, 0], [1.4, 4, 0], [.4, 4, 0]]
    corners = np.asarray(vertices); faces = []; trunk = quad(vertices, faces, corners[[0, 1, 2, 4]], True)
    left = quad(vertices, faces, corners[[4, 3, 5, 6]], True); right = quad(vertices, faces, corners[[3, 2, 7, 8]], True)
    arcs = [arc('end', 0, 1, 'insertion'), arc('right', 1, 2, 'side'), arc('join_r', 2, 3, 'seam'), arc('join_l', 3, 4, 'seam'), arc('left', 4, 0, 'side')]
    arcs += [arc('cleft_l', 3, 5, 'cleft'), arc('origin_l', 5, 6, 'origin'), arc('outer_l', 6, 4, 'side')]
    arcs += [arc('outer_r', 2, 7, 'side'), arc('origin_r', 7, 8, 'origin'), arc('cleft_r', 8, 3, 'cleft')]
    patches = [dict(id='belly', head_ids=['left', 'right'], source_triangles=trunk, boundary=border('end', 'right', 'join_r', 'join_l', 'left'))]
    patches += [dict(id='left', head_ids=['left'], source_triangles=left, boundary=border('-join_l', 'cleft_l', 'origin_l', 'outer_l'))]
    patches += [dict(id='right', head_ids=['right'], source_triangles=right, boundary=border('-join_r', 'outer_r', 'origin_r', 'cleft_r'))]
    return dict(vertices=vertices, triangles=faces, heads=[dict(id='left', label='Left head'), dict(id='right', label='Right head')], arcs=arcs, patches=patches,
                settings=dict(rings=4, iterations=4, regularization=4.))

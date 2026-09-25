from dataclasses import dataclass
from math import sqrt


@dataclass(frozen=True)
class FiberSurfaceSpec:
    construction_mode: str = "LOFT"
    close_across_fibers: bool = False
    closed_along_fibers: bool = False
    flip_normals: bool = False
    patch_resolution: int = 4
    target_node_count: int = 0
    exact_samples: bool = False
    parameter_stations: tuple = ()


@dataclass(frozen=True)
class FiberSurfaceResult:
    vertices: tuple
    faces: tuple
    rows: tuple = ()
    closed_along_fibers: bool = False


def evaluate_fiber_surface(ordered_points, spec):
    mode = str(spec.construction_mode or "LOFT").upper()
    if mode == "LOOP_PATCH":
        return _evaluate_loop_patch(ordered_points, spec)
    if mode != "LOFT":
        raise ValueError(f"Unsupported Fiber Surface mode: {mode}.")
    return _evaluate_loft(ordered_points, spec)


def _evaluate_loft(ordered_points, spec):
    prepared = _prepare_spec_rows(ordered_points, spec)
    count = len(prepared[0])
    vertices, faces = _flatten(prepared), _grid_faces(len(prepared), count, spec)
    return FiberSurfaceResult(tuple(vertices), tuple(_oriented_faces(faces, spec.flip_normals)), _frozen_rows(prepared), bool(spec.closed_along_fibers))


def _prepare_spec_rows(points, spec):
    if spec.parameter_stations:
        from .free_surface_stations import prepare
        if spec.closed_along_fibers: raise ValueError('FREE_CORRESPONDENCE_CLOSED')
        return prepare(points, spec.parameter_stations)
    if spec.exact_samples:
        from .free_surface import prepare_rows
        return prepare_rows(points, spec.closed_along_fibers, multiplier=4)
    return prepare_loft_rows(points, spec.target_node_count, spec.closed_along_fibers)


def prepare_loft_rows(ordered_points, target_count=0, closed=False, densify=True):
    rows = [[_co3(point) for point in row] for row in ordered_points]
    if not rows:
        return []
    _validate_loft_rows(rows)
    count = int(target_count) or len(rows[0])
    prepared = [_resample(row, count, bool(closed)) for row in rows]
    prepared = _align_closed_rows(prepared) if bool(closed) else prepared
    return _densify_rows(prepared, 3 if closed else 0) if densify else prepared


def build_loft_topology(row_count, column_count, close_across=False, closed_along=False, flip=False):
    spec = FiberSurfaceSpec(close_across_fibers=close_across, closed_along_fibers=closed_along, flip_normals=flip)
    return _oriented_faces(_grid_faces(int(row_count), int(column_count), spec), flip)


def flatten_surface_rows(rows):
    return [_co3(point) for row in rows for point in row]


def _validate_loft_rows(rows):
    if len(rows) < 2:
        raise ValueError("LOFT requires at least two Fibers.")
    count = len(rows[0])
    if count < 2 or any(len(row) != count for row in rows):
        raise ValueError("LOFT Fibers must have the same node count.")


def _resample(points, count, closed):
    samples = list(points) + ([points[0]] if closed and _dist(points[0], points[-1]) > 1.0e-9 else [])
    spans = _cumulative_lengths(samples)
    if not samples or count <= 0:
        return []
    if spans[-1] <= 1.0e-9:
        return [samples[0] for _index in range(count)]
    divisor = float(count if closed else max(1, count - 1))
    return [_sample_at(samples, spans, spans[-1] * index / divisor) for index in range(count)]


def _cumulative_lengths(points):
    spans = [0.0]
    for first, second in zip(points, points[1:]):
        spans.append(spans[-1] + _dist(first, second))
    return spans


def _sample_at(points, spans, target):
    for index in range(len(spans) - 1):
        if spans[index + 1] >= target:
            width = max(1.0e-9, spans[index + 1] - spans[index])
            return _lerp(points[index], points[index + 1], (target - spans[index]) / width)
    return points[-1]


def _align_closed_rows(rows):
    if len(rows) < 2:
        return rows
    output = [rows[0]]
    for row in rows[1:]:
        output.append(_best_closed_row(output[-1], row))
    return output


def _best_closed_row(reference, row):
    forward = _best_shift(reference, row)
    reverse = _best_shift(reference, list(reversed(row)))
    return min((forward, reverse), key=lambda item: _row_score(reference, item))


def _best_shift(reference, row):
    candidates = [row[index:] + row[:index] for index in range(len(row))]
    return min(candidates, key=lambda item: _row_score(reference, item))


def _row_score(reference, row):
    return sum(_dist_sq(first, second) for first, second in zip(reference, row)) / float(max(1, len(row)))


def _densify_rows(rows, minimum):
    step = _average_row_step(rows)
    output = [rows[0]]
    for first, second in zip(rows, rows[1:]):
        inserts = _row_inserts(first, second, step, minimum)
        output.extend([[_lerp(a, b, index / float(inserts + 1)) for a, b in zip(first, second)] for index in range(1, inserts + 1)])
        output.append(second)
    return output


def _average_row_step(rows):
    lengths = [_dist(first, second) for row in rows for first, second in zip(row, row[1:])]
    return max(1.0e-6, sum(lengths) / float(max(1, len(lengths))))


def _row_inserts(first, second, step, minimum):
    average = sum(_dist(a, b) for a, b in zip(first, second)) / float(len(first))
    return max(int(minimum), int(round((average / step) - 1.0e-6)) - 1)


def _grid_faces(row_count, column_count, spec):
    pairs = [(index, index + 1) for index in range(row_count - 1)]
    if bool(spec.close_across_fibers) and row_count > 2:
        pairs.append((row_count - 1, 0))
    columns = range(column_count) if bool(spec.closed_along_fibers) and column_count > 2 else range(column_count - 1)
    return [_quad(first, second, column, column_count) for first, second in pairs for column in columns]


def _quad(first, second, column, count):
    following = (column + 1) % count
    return first * count + column, second * count + column, second * count + following, first * count + following


def _evaluate_loop_patch(ordered_points, spec):
    if len(ordered_points) != 1:
        raise ValueError("LOOP_PATCH requires exactly one LOOP Fiber.")
    loop = [_co3(point) for point in ordered_points[0]]
    if spec.exact_samples: _check_free_patch(loop, spec.patch_resolution)
    _validate_patch_loop(loop)
    vertices, faces = _triangulated_patch(loop, spec.patch_resolution, spec.exact_samples)
    return FiberSurfaceResult(tuple(vertices), tuple(_oriented_faces(faces, spec.flip_normals)), (), True)


def _check_free_patch(loop, level):
    from .free_surface import check_budget
    count = max(1, len(loop) - 2)
    check_budget(count * (level + 1) * (level + 2) // 2, count * level * level, multiplier=2)


def _validate_patch_loop(loop):
    if len(loop) < 3:
        raise ValueError("LOOP_PATCH requires at least three boundary samples.")
    normal = _newell_normal(loop)
    if _length_sq(normal) <= 1.0e-16:
        raise ValueError("LOOP_PATCH boundary is degenerate.")
    if _has_projected_intersection(loop, _best_fit_normal(loop)):
        raise ValueError("LOOP_PATCH boundary self-intersects.")


def _triangulated_patch(loop, resolution, exact=False):
    points = _project_loop(loop, _best_fit_normal(loop))
    sources, triangles = _patch_source_triangles(loop, points, exact)
    vertices, faces, keys = _subdivided_triangles(sources, triangles, resolution)
    fixed = _fixed_patch_indices(keys, len(loop))
    vertices = _fair_patch(vertices, faces, fixed)
    return _boundary_last(vertices, faces, keys, len(loop))


def _patch_source_triangles(loop, points, exact=False):
    try:
        return loop, _ear_triangles(points, exact)
    except ValueError:
        if not _is_convex_polygon(points):
            raise
    center = _scale(tuple(map(sum, zip(*loop))), 1.0 / float(len(loop)))
    order = _oriented_polygon_indices(points)
    triangles = [(len(loop), order[index], order[(index + 1) % len(order)]) for index in range(len(order))]
    return loop + [center], triangles


def _is_convex_polygon(points):
    signs = []
    for index in range(len(points)):
        value = _orient2(points[index - 1], points[index], points[(index + 1) % len(points)])
        if abs(value) > 1.0e-12:
            signs.append(value > 0.0)
    return bool(signs) and len(set(signs)) == 1


def _ear_triangles(points, exact=False):
    remaining = _oriented_polygon_indices(points)
    triangles = []
    while len(remaining) > 3:
        ear = _first_ear(points, remaining, exact)
        if ear < 0:
            raise ValueError("LOOP_PATCH boundary cannot be triangulated.")
        triangles.append(_ear_at(remaining, ear))
        remaining.pop(ear)
    triangles.append(tuple(remaining))
    return triangles


def _oriented_polygon_indices(points):
    area = sum(_orient2((0.0, 0.0), points[i], points[(i + 1) % len(points)]) for i in range(len(points)))
    return list(range(len(points))) if area > 0.0 else list(reversed(range(len(points))))


def _first_ear(points, polygon, exact=False):
    for position in range(len(polygon)):
        triangle = _ear_at(polygon, position)
        if _is_ear(points, polygon, triangle, exact):
            return position
    return -1


def _ear_at(polygon, position):
    count = len(polygon)
    return polygon[(position - 1) % count], polygon[position], polygon[(position + 1) % count]


def _is_ear(points, polygon, triangle, exact=False):
    a, b, c = (points[index] for index in triangle)
    if _orient2(a, b, c) <= 1.0e-12:
        return False
    others = (index for index in polygon if index not in triangle)
    inside = _inside_closed_triangle if exact else _strictly_inside_triangle
    return not any(inside(points[index], a, b, c) for index in others)


def _inside_closed_triangle(point, a, b, c):
    # Do not clip a diagonal through retained boundary samples, stranding them.
    return min(_orient2(a, b, point), _orient2(b, c, point), _orient2(c, a, point)) >= -1.0e-12


def _strictly_inside_triangle(point, a, b, c):
    return min(_orient2(a, b, point), _orient2(b, c, point), _orient2(c, a, point)) > 1.0e-12


def _subdivided_triangles(loop, triangles, resolution):
    level = max(1, min(64, int(resolution)))
    vertices, faces, key_to_index = [], [], {}
    for triangle_index, triangle in enumerate(triangles):
        _subdivide_triangle(loop, triangle, triangle_index, level, vertices, faces, key_to_index)
    keys = [None] * len(vertices)
    for key, index in key_to_index.items():
        keys[index] = key
    return vertices, faces, keys


def _subdivide_triangle(loop, triangle, triangle_index, level, vertices, faces, key_to_index):
    grid = {}
    for first in range(level + 1):
        for second in range(level + 1 - first):
            weights = (first, second, level - first - second)
            grid[first, second] = _patch_vertex(loop, triangle, triangle_index, weights, level, vertices, key_to_index)
    faces.extend(_triangle_grid_faces(grid, level))


def _patch_vertex(loop, triangle, triangle_index, weights, level, vertices, key_to_index):
    key = _patch_vertex_key(triangle, triangle_index, weights, level)
    if key not in key_to_index:
        key_to_index[key] = len(vertices)
        vertices.append(_barycentric_point(loop, triangle, weights, level))
    return key_to_index[key]


def _patch_vertex_key(triangle, triangle_index, weights, level):
    if level in weights:
        return "v", triangle[weights.index(level)]
    if 0 in weights:
        return _edge_vertex_key(triangle, weights, weights.index(0))
    return "t", triangle_index, *weights


def _edge_vertex_key(triangle, weights, zero_index):
    live = [index for index in range(3) if index != zero_index]
    first, second = triangle[live[0]], triangle[live[1]]
    low, high = sorted((first, second))
    high_weight = weights[live[0]] if first == high else weights[live[1]]
    return "e", low, high, high_weight


def _barycentric_point(loop, triangle, weights, level):
    values = [loop[index] for index in triangle]
    return tuple(sum(values[i][axis] * weights[i] for i in range(3)) / float(level) for axis in range(3))


def _triangle_grid_faces(grid, level):
    faces = []
    for first in range(level):
        for second in range(level - first):
            faces.append((grid[first, second], grid[first + 1, second], grid[first, second + 1]))
            if second < level - first - 1:
                faces.append((grid[first + 1, second], grid[first + 1, second + 1], grid[first, second + 1]))
    return faces


def _fixed_patch_indices(keys, count):
    fixed = set()
    for index, key in enumerate(keys):
        is_vertex = key[0] == "v" and int(key[1]) < count
        is_edge = key[0] == "e" and _boundary_pair(key[1], key[2], count)
        if is_vertex or is_edge:
            fixed.add(index)
    return fixed


def _boundary_pair(first, second, count):
    return abs(int(first) - int(second)) == 1 or {int(first), int(second)} == {0, count - 1}


def _fair_patch(vertices, faces, fixed, passes=4):
    adjacency = _vertex_adjacency(len(vertices), faces)
    current = list(vertices)
    for _pass in range(passes):
        current = [_fair_vertex(current, adjacency, index, fixed) for index in range(len(current))]
    return current


def _vertex_adjacency(count, faces):
    adjacency = [set() for _index in range(count)]
    for face in faces:
        for first, second in zip(face, face[1:] + face[:1]):
            adjacency[first].add(second)
            adjacency[second].add(first)
    return adjacency


def _fair_vertex(vertices, adjacency, index, fixed):
    if index in fixed or not adjacency[index]:
        return vertices[index]
    average = _scale(tuple(map(sum, zip(*(vertices[item] for item in adjacency[index])))), 1.0 / len(adjacency[index]))
    return _lerp(vertices[index], average, 0.5)


def _boundary_last(vertices, faces, keys, count):
    boundary = [keys.index(("v", index)) for index in range(count)]
    order = [index for index in range(len(vertices)) if index not in set(boundary)] + boundary
    remap = {source: target for target, source in enumerate(order)}
    return [vertices[index] for index in order], [tuple(remap[index] for index in face) for face in faces]


def _newell_normal(loop):
    normal = (0.0, 0.0, 0.0)
    for current, following in zip(loop, loop[1:] + loop[:1]):
        term = ((current[1] - following[1]) * (current[2] + following[2]),
                (current[2] - following[2]) * (current[0] + following[0]),
                (current[0] - following[0]) * (current[1] + following[1]))
        normal = _add(normal, term)
    return normal


def _best_fit_normal(loop):
    center = _scale(tuple(map(sum, zip(*loop))), 1.0 / float(len(loop)))
    covariance = _covariance(loop, center)
    normal = _normalized(_newell_normal(loop))
    scale = max(1.0e-12, max(sum(abs(value) for value in row) for row in covariance))
    for _iteration in range(32):
        candidate = _add(normal, _scale(_matrix_vector(covariance, normal), -1.0 / scale))
        normal = _normalized(candidate) if _length_sq(candidate) > 1.0e-20 else normal
    return normal


def _covariance(points, center):
    offsets = [tuple(point[index] - center[index] for index in range(3)) for point in points]
    return tuple(tuple(sum(offset[row] * offset[column] for offset in offsets) for column in range(3))
                 for row in range(3))


def _matrix_vector(matrix, vector):
    return tuple(sum(matrix[row][column] * vector[column] for column in range(3)) for row in range(3))


def _normalized(vector):
    return _scale(vector, 1.0 / sqrt(max(1.0e-30, _length_sq(vector))))


def _has_projected_intersection(loop, normal):
    points = _project_loop(loop, normal)
    count = len(points)
    return any(_segments_cross(points[i], points[(i + 1) % count], points[j], points[(j + 1) % count])
               for i in range(count) for j in range(i + 1, count) if not _adjacent_edges(i, j, count))


def _project_loop(loop, normal):
    center = _scale(tuple(map(sum, zip(*loop))), 1.0 / float(len(loop)))
    reference = tuple(1.0 if index == min(range(3), key=lambda i: abs(normal[i])) else 0.0 for index in range(3))
    first = _normalized(_cross(normal, reference))
    second = _cross(normal, first)
    return [(_dot(_add(point, _scale(center, -1.0)), first), _dot(_add(point, _scale(center, -1.0)), second)) for point in loop]


def _cross(first, second):
    return (first[1] * second[2] - first[2] * second[1], first[2] * second[0] - first[0] * second[2],
            first[0] * second[1] - first[1] * second[0])


def _dot(first, second):
    return sum(a * b for a, b in zip(first, second))


def _adjacent_edges(first, second, count):
    return first == second or (first + 1) % count == second or (second + 1) % count == first


def _segments_cross(a, b, c, d):
    first, second = _orient2(a, b, c), _orient2(a, b, d)
    third, fourth = _orient2(c, d, a), _orient2(c, d, b)
    return first * second < -1.0e-12 and third * fourth < -1.0e-12


def _orient2(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _oriented_faces(faces, flip):
    return [_flipped_face(face) for face in faces] if bool(flip) else [tuple(face) for face in faces]


def _flipped_face(face):
    if len(face) == 4:
        return face[0], face[3], face[2], face[1]
    return tuple(reversed(face))


def _flatten(rows):
    return [point for row in rows for point in row]


def _frozen_rows(rows):
    return tuple(tuple(point for point in row) for row in rows)


def _co3(point):
    return float(point[0]), float(point[1]), float(point[2])


def _lerp(first, second, factor):
    return tuple(a + (b - a) * factor for a, b in zip(first, second))


def _add(first, second):
    return tuple(a + b for a, b in zip(first, second))


def _scale(point, factor):
    return tuple(value * factor for value in point)


def _dist_sq(first, second):
    return sum((a - b) ** 2 for a, b in zip(first, second))


def _dist(first, second):
    return sqrt(_dist_sq(first, second))


def _length_sq(point):
    return sum(value * value for value in point)

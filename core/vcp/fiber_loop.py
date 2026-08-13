def close_loop(points, eps=1.0e-9):
    pts = [point.copy() for point in tuple(points or ())]
    if not pts or (pts[0] - pts[-1]).length <= eps:
        return pts
    return pts + [pts[0].copy()]


def closed_spans(points):
    pts = close_loop(points)
    spans = [0.0]
    for i in range(len(pts) - 1):
        spans.append(spans[-1] + (pts[i + 1] - pts[i]).length)
    return pts, spans, spans[-1] if spans else 0.0


def resample_closed(points, count):
    pts, spans, total = closed_spans(points)
    if not pts or count <= 0:
        return []
    if total <= 1.0e-9:
        return [pts[0].copy() for _ in range(count)]
    return _closed_samples(pts, spans, total, count)


def _closed_samples(points, spans, total, count):
    out, segment = [], 0
    for index in range(count):
        target = total * index / float(count)
        while segment + 2 < len(spans) and spans[segment + 1] < target:
            segment += 1
        out.append(_segment_point(points[segment], points[segment + 1],
                                  spans[segment], spans[segment + 1], target))
    return out


def _closed_point(points, spans, target):
    for i in range(len(spans) - 1):
        if spans[i + 1] >= target:
            return _segment_point(points[i], points[i + 1], spans[i], spans[i + 1], target)
    return points[0].copy()


def _segment_point(a, b, start, end, target):
    span = max(1.0e-9, end - start)
    return a.lerp(b, (target - start) / span)


def loop_pin_targets(route, anchors, count):
    marks, total = _anchor_marks(route, anchors)
    used, out = set(), {}
    for mark, anchor in zip(marks, anchors):
        base = int(round((mark / max(total, 1.0e-9)) * count)) % max(1, count)
        index = _free_index(base, used, count)
        used.add(index)
        out[index] = anchor.copy()
    return out


def _anchor_marks(route, anchors):
    pts, spans, total = closed_spans(route)
    cursor, marks = 0, []
    for anchor in anchors:
        cursor = _anchor_index(pts, anchor, cursor)
        marks.append(spans[cursor])
    return marks, total


def _anchor_index(points, anchor, start, eps=1.0e-6):
    for index in range(start, len(points)):
        if (points[index] - anchor).length <= eps:
            return index
    return start


def _free_index(index, used, count):
    for step in range(max(1, count)):
        trial = (index + step) % max(1, count)
        if trial not in used:
            return trial
    return 0

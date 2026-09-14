"""Slow, exact expanded preparation for qualification only; not a production mode."""


class ReferenceRoadmapPreparation:
    def __init__(self, planner):
        self.planner = planner

    def unique(self, original, candidates):
        return self.planner.append_access_points(original, candidates)

    def neighbors(self, points, original, limit):
        return self.planner.append_access_neighbors(points, original, limit)

    def anchors(self, state, points, graph, start, end):
        result = self.planner._checked_anchor_neighbors(state, points, graph, start, end)
        yield "ANCHOR_VALIDATION"
        return result

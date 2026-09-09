"""Connected penetration patches used to reject newly introduced contacts."""
import numpy as np


def components(indices, surface, affected):
    pending, neighbors = set(affected), {}
    for index in affected:
        for vertex in indices[index]:
            neighbors.setdefault(int(vertex),set()).add(index)
    output = []
    while pending:
        visited = flood(pending, neighbors, indices)
        points = surface[sorted(visited)].reshape(-1,3)
        output.append(dict(low=points.min(0).tolist(),high=points.max(0).tolist(),triangles=sorted(visited)))
    return output


def flood(pending, neighbors, indices):
    queue, visited = [pending.pop()], set()
    while queue:
        index = queue.pop()
        visited.add(index)
        adjacent = set.union(*(neighbors[int(v)] for v in indices[index])) & pending
        pending.difference_update(adjacent)
        queue.extend(adjacent)
    return visited


def retained(before, after, tolerance):
    if "material_triangles" in before and "material_triangles" in after:
        from .contact_repair import covered
        return covered(before,after)
    old, new = before.get("components",[]), after.get("components",[])
    return all(any(covered(part, previous, tolerance) for previous in old) for part in new)


def covered(part, previous, tolerance):
    return bool(np.all(np.array(part["low"]) >= np.array(previous["low"])-tolerance)
                and np.all(np.array(part["high"]) <= np.array(previous["high"])+tolerance))

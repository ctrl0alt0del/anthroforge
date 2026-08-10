import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prototype_topology_field as field_test


BASE_SOLVE = field_test.solve_field
ROBUST_PASSES = 4
GUIDE_CUTOFF = math.radians(24.0)


def row_error(solution, row):
    index, value, _weight = row
    dot = np.real(solution.field[index] * np.conjugate(value))
    return 0.25 * math.acos(float(np.clip(dot, -1.0, 1.0)))


def robust_weight(solution, row):
    if row[2] >= 1000.0:
        return row
    ratio = min(1.0, row_error(solution, row) / GUIDE_CUTOFF)
    scale = max(0.05, (1.0 - (ratio * ratio)) ** 2)
    return row[0], row[1], row[2] * scale


def robust_solve(inputs, rows):
    solution = BASE_SOLVE(inputs, rows)
    weighted = tuple(rows)
    for _pass in range(ROBUST_PASSES):
        weighted = tuple(robust_weight(solution, row) for row in rows)
        solution = BASE_SOLVE(inputs, weighted)
    return solution


def main():
    field_test.solve_field = robust_solve
    field_test.main()


if __name__ == "__main__":
    main()

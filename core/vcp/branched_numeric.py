"""Prepared branched Muscle requests share the standard numerical publication result."""
from dataclasses import dataclass
from time import perf_counter
from .muscle_numeric import MuscleNumericBatchResult, MuscleNumericResult, _invalid_result, _readonly_array
from .branched_surface import assemble
from .prepared_inflation import inflate_assembly
import numpy as np


@dataclass(frozen=True)
class BranchedMuscleRequest:
    muscle_id: str
    assembly: object
    part_specs: tuple

    @property
    def spec(self):
        return self.part_specs[0]


def execute_mixed(requests, backend):
    from .muscle_numeric import execute_muscle_batch
    started = perf_counter()
    ordinary = tuple(r for r in requests if not isinstance(r, BranchedMuscleRequest))
    batch = execute_muscle_batch(ordinary, backend)
    regular = iter(batch.results)
    results = tuple(evaluate(request, backend) if isinstance(request, BranchedMuscleRequest)
                    else next(regular) for request in requests)
    return MuscleNumericBatchResult(results, batch.backend, (perf_counter()-started)*1000, batch.workers, batch.parallel)


def evaluate(request, backend):
    try:
        main, branches = inflate_assembly(request.assembly, request.part_specs, backend)
        base, faces = assemble(request.assembly)
        inflated, _ = assemble(request.assembly, main, branches)
        return MuscleNumericResult(request.muscle_id, _readonly_array(base, np.float64, (-1, 3)),
            _readonly_array(inflated, np.float64, (-1, 3)), _readonly_array(faces, np.int64, (-1, 4)), 0, 0)
    except (ValueError, RuntimeError) as error:
        return _invalid_result(request.muscle_id, str(error))

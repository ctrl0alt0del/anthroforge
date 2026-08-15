# Fiber V2 Package 4.1 — cached-metric lazy A* search

## Status and scope

Package 4.1 is a separate planner entry point. Package 4 remains unchanged as the
benchmark and route-parity reference. Package 4.1 changes only the implementation
of repeated shortest-path search; direct routing, surface routing, edge selection,
candidate samples, collider policy, owner contact, exact-count handoff, and final
validation remain identical.

## Problem

Package 4 validates only edges on the current shortest path. When one or more are
invalid, it restarts A* on almost the same graph. The production skeleton fixture
performs 112 complete searches, 115 collision batches, and 223 edge validations.
Graph search alone costs about 277 ms.

## Algorithm

Package 4.1 keeps Package 4's LazySP decisions and makes its repeated A* search
operate on one cached Euclidean graph metric:

1. Build the full symmetric Euclidean distance matrix once for each fixed candidate
   graph; the largest current graph uses under 0.5 MiB.
2. Reuse those scalar edge costs and goal heuristics for every LazySP A* pass.
3. Validate only unknown edges on the selected path, exactly as Package 4 does.
4. Add rejected edges to the solve-local invalid set and repeat until the shortest
   path is fully validated or no route remains.
5. Apply the unchanged collision-checked shortcut and exact-count validator.

The collision workload is intentionally unchanged. Precomputing removes repeated
NumPy norm calls from all graph expansions while retaining canonical heap order,
strict relaxation, and the exact Package 4 route.

Two more aggressive approaches were measured and rejected. A path-frontier batch
cut 112 searches to 15 but raised tested pairs from 33,941 to 124,949. Python LPA*
cut full searches to two, but its `g/rhs` repair expanded 566 vertices and measured
1.21 s versus Package 4's 0.94 s. On these small graphs, cached scalar A* is faster
than maintaining an incremental search tree in Python. A native incremental graph
kernel remains possible only if cached A* is still material after collision work.

## Determinism and compatibility

- Candidate nodes and neighbor ordering are inherited from Package 4.
- Edge canonicalization and batch ordering are stable.
- Unknown, valid, and invalid edge sets are solve-local.
- Package 4.1 must return the same route, exact reference, pins, contacts, and
  termination as Package 4 for every existing deterministic fixture.
- Every returned edge still passes independent Package 3 validation.
- No Blender runtime, persistence, migration, or V1 behavior is changed.

## Diagnostics

Planner diagnostics add:

- `graph_searches`;
- `edge_batches`;
- `graph_metric_builds`;
- `graph_expansions`.

## Gates

- Existing Package 4 planner tests pass unchanged for both entry points.
- Each fixed candidate graph builds its metric once.
- Skeleton tested edges and collision pairs do not exceed Package 4.
- Package 4.1 is faster than Package 4 on both roadmap production fixtures.
- Surface-only work does not regress beyond 5% median process variance.
- Routes and exact references match Package 4 within `1e-9` BU.
- Independent node/edge residuals remain zero.
- Visual Blender comparisons show no route change.
- Every new or modified function remains at most 15 lines.

## Implementation and qualification result

Package 4.1 is implemented in `core/vcp/v2/planner.py` as the separate
`plan_reference_v41` entry point. Package 4 remains available unchanged. The dense
metric is solve-local, deterministic, and discarded with the planner state.

Blender 5.0.1, Windows x64, AMD Family 25 Model 97; medians are five paired calls
against one already-built immutable collider snapshot:

| Fixture | Triangles | V1 | V1 strict | Package 4 | Package 4.1 | P4 time reduction | P4.1 strict |
|---|---:|---:|---|---:|---:|---:|---|
| `skeleton_comb_base/FIBER_1` | 39,180 | 75.47 ms | valid | 739.77 ms | 489.44 ms | 33.84% | valid |
| `skull_muscles/FIBER_14` | 30,544 | 140.36 ms | unsafe | 300.48 ms | 233.12 ms | 22.42% | valid |
| `skull_muscles/FIBER_1` | 30,544 | 34.58 ms | unsafe | 339.12 ms | 333.15 ms | 1.76% | valid |
| `skull_muscles_skin/FIBER_1` | 30,544 | 35.91 ms | unsafe | 338.46 ms | 325.19 ms | 3.92% | valid |

For every row, Package 4.1 and Package 4 have identical termination, mode,
corridor, pin indices, and exact reference (`max_reference_delta = 0.0`). Tested
edges and triangle pairs are also identical. The skeleton case remains 223 edges
and 33,941 tested pairs; skull FIBER_14 remains 83 edges and 8,680 pairs.

The controlled skull/skull-skin comparison uses the same 30,544-triangle snapshot.
Both Package 4 and Package 4.1 references are bit-identical between the two files.
Draft Skin is therefore excluded from candidate generation and collision input as
intended.

## Profile interpretation

On the skeleton fixture, a traced Package 4.1 run measured approximately 479 ms:

- cached-metric A* and surrounding compatibility search: 52.9 ms exclusive;
- all segment-batch collision validation: 373.4 ms inclusive;
- native exact distances: 121.1 ms exclusive;
- native containment: 39.6 ms exclusive;
- native broad phase: 26.9 ms exclusive;
- candidate generation, shortcut, handoff, and final validation: the remainder.

Under cProfile, the 112 cached A* calls account for about 106 ms cumulative,
including 2,455 node expansions. They are still repeated logical searches, but no
longer repeat Euclidean NumPy norms. Avoiding the count with Python LPA* was slower;
moving graph repair to native code is not justified until the larger collision and
binding-dispatch costs are reduced and reprofiled.

The profile's preloaded native-binding experiment reduced the same planner from
about 494 ms to 277 ms. That points to repeated Python native-library/status/path
orchestration as the next contained optimization; it is deliberately outside the
A*-only Package 4.1 change.

## Visual and benchmark artifacts

- `artifacts/fiber_v2_package41/skeleton_fiber1_comparison.png`: true Blender/Eevee
  V1 / Package 4 / Package 4.1 render.
- `artifacts/fiber_v2_package41/skull_fiber14_comparison.png`: true Blender/Eevee
  render showing the unsafe V1 edge and exact Package 4/4.1 parity.
- `artifacts/fiber_v2_package41/benchmark_comparison.png`: four-fixture timing chart.
- `artifacts/fiber_v2_package41/profile_skeleton_fiber1.json`: phase timings,
  cProfile rows, collider manifest, and source/snapshot hashes.
- Adjacent benchmark JSON files contain all points, diagnostics, independent
  validation results, and immutable source hashes.

Validation: 378/378 unit tests pass (one pre-existing expected failure), all 11
focused planner tests pass, the function-size ratchet passes, and `git diff --check`
reports no whitespace errors. The source `.blend` hashes match their
captured benchmark hashes after every run.

## Research basis

- Dellin and Srinivasa, *A Unifying Formalism for Shortest Path Problems with
  Expensive Edge Evaluations via Lazy Best-First Search over Paths with Edge
  Selectors*, ICAPS 2016.
- Koenig, Likhachev, and Furcy, *Lifelong Planning A\**, Artificial Intelligence
  2004. LPA* informed and was evaluated for the rejected incremental prototype.

# Conditional pin-exit recovery

Production V2/V3 preserve DIRECT, surface, ordinary roadmap and expanded-candidate
strategy order. Only a failed corridor search enters the two new stages:

1. Broad, collision-checked pin-exit sampling and augmented-graph connection.
2. A bounded bidirectional local tree connector when sampling alone cannot connect.

No Boolean union, pin repair/resnapping, solver-policy change, CUDA dependency or
new worker pool is part of the planner recovery itself. Successful ordinary routes and V3 warm
planner bypasses do no recovery work. Propagated SCP edits remain attachment-only.

## Accepted policy

- 2,048 Fibonacci-sphere directions at 2, 2.5 and 4 sampling-scale distances.
- Sampling scale is max(radius, 4 clearance slack, numeric floor, 1e-7).
  This floor changes sample placement, never collision clearance.
- Both authored span ends are sampled; new free nodes have no owner exemption.
- Initial connections use 32 nearest opposite-component nodes.
- Augmentation preserves old coordinates, duplicates and links; new nodes use
  48 nearest neighbors plus both anchor indices, reciprocal sorted adjacency.
- Request-local PCG64 seeds 914/915 and stable ordering reproduce the reference.
- Alternating 32-target tree batches; 25% goal bias; local half-widths
  8/16/32/64 scales; steps .5/1/2/4 scales; actual pin step 2.5 scales.
- Collision-failed tree nodes restrict their sampling domain to 8 scales.
- At most 256 alternating batches per side, at most two side attempts per span.
  This is at most 32,768 growth targets, not 8,192 total collision checks.
- First validated connection is retained. Existing shortcutting and exact-count
  handoff remain authoritative. Handoff failure does not restart the search.

This is the accepted bounded adaptation, not a completeness or shortest-path
claim. Research background: [dynamic-domain RRT](https://lavalle.pl/papers/YerJaiSimLav05.pdf)
and [RRT-Connect](https://lavalle.pl/papers/KufLav00.pdf).

## Implementation and lifecycle

`planner_session` owns activation; `planner_pin_recovery` coordinates stages;
`planner_pin_tree` owns pure-array trees; `planner_pin_graph` owns collision proofs
and deterministic graph operations. There are no production experiment imports.

Collision proofs are indexed and local to one immutable request/span. Augmentation
only appends points, permitting unchanged-edge proof reuse. No proof crosses a
request, collider generation, owner policy or point mutation. Cancellation closes
the generator and releases trees/proofs. Existing engine publication rules apply.

Native ABI remains 3. Packaged build v3_13 adds bounded exact nearest-neighbor
preparation (capability 268435456). Existing collision kernels are unchanged.
Policy/engine versions invalidate old route/result caches; load never recomputes
persisted geometry automatically. Recovery exposes detailed outcomes, query and
growth counts, cache hits, and the planner's full phase timings.

Native lazy A* retains its bounded atomic 512-search call. It may exceed 20 ms;
resumable preparation is not a promise of a sub-20-ms complete planner slice.
The main-thread runtime drains planner microbatches inside its existing 12-ms
allowance, then yields. It stops draining when planning completes; numerical
solver scheduling and accepted-step caps are unchanged.

## Qualification

The archived prepared 76-Fiber fixture achieved 65 existing routes, five sampling
recoveries (155/156/162/163/164), and six local-search recoveries
(321/322/323/324/338/339). This precondition includes externally prepared surfaces
and bindings. It is not a 76/76 guarantee on an unprepared original scene.

`tools/fiber_pin_recovery_qualification.py` replays frozen geometry and requests,
performs no Boolean or resnap, and checks exact planner-reference parity in real
Blender processes. It compares production with pin recovery disabled against
integrated production; the accepted experimental route is frozen data, not an
executable reference solver. Ordinary failures are recorded rather than asserted
away. `--solver` separately records solver results. Cold/warm planner
timers include policy, setup, all attempts and exact-count handoff; extra audit,
file I/O, solving, UI and downstream work are excluded.

`tools/fiber_pin_recovery_foreground.py` replays frozen evaluated meshes/bindings
in a disposable Blender process and runs actual Preview/Recompute operators using
normal timers. It never saves the source. Replay is test fixture setup only.

## Measured integration (2026-09-15)

Three fresh Blender processes, rotated paired order, 76 Fibers, cold and warm:
all 912 measured planner calls match the frozen prepared reference bit-for-bit,
with independent clearance checks, exact counts, and zero pin residual. Source
SHA-256 remains `2991dfa26ee6d3d70a51dfe93b88b75046a9410b624e8b93f2f5c09cee12e0d2`.

| Full planner, ms | Reference cold | Production cold | Reference warm | Production warm |
|---|---:|---:|---:|---:|
| Median | 237.51 | 232.46 | 141.44 | 143.61 |
| Mean | 542.03 | 488.39 | 450.72 | 401.60 |
| p95 | 2708.03 | 2175.04 | 2608.95 | 2078.75 |
| Maximum | 3124.12 | 2330.57 | 3052.91 | 2345.37 |

The six local-search cases improve 14.8–25.7% in paired cold per-Fiber medians.
The five sampling-only cases improve 2.8–15.5%. This is comparison against the
accepted experimental implementation, not against the old unsuccessful planner.
Successful existing routes perform no new recovery work. A separate production
policy-off/on retest of 15 noisy ordinary cases showed no aggregate slowdown,
but per-case outliers remained; a strict 5% per-case timing gate is not established.

Foreground, GUI event-loop runs replayed the prepared mesh/binding fixture and
waited for load checks to finish before timing actual operators. No manual timer
draining, Boolean, resnap, solver mocking, or source saving occurred.

| Actual complete operator flow | FIBER_155 | FIBER_321 |
|---|---:|---:|
| Planner Preview | 8796.87 ms | 9003.65 ms |
| Cold Recompute, through downstream completion | 9750.05 ms | 9723.32 ms |
| Warm Recompute, through downstream completion | 8397.52 ms | 6458.65 ms |
| Recompute result | validated BUDGET_EXHAUSTED | validated STALLED |

Both Recompute results became CURRENT and incremented generation exactly once.
Preview stayed STALE and did not alter persistent points/generation. Warm runs
bypassed the planner. Runtime batching preserved FIBER_155 planner and final
geometry exactly against the one-microbatch-per-tick control.

These UI numbers remain slow and are not equivalent to the planner-only table.
The existing runtime's Preview path waits for the solver package before returning
the planner result; it is not a planner-only latency measurement. FIBER_321's plan
was ready at 3.56 seconds in cold Recompute; job termination was at 8.67 seconds,
with downstream completion at 9.72 seconds. This delivery does not change solver
termination, preview publication semantics, or downstream generation.

Native pin-recovery A* reached 281.18 ms in the paired benchmark. Other new
phase maxima reached 40.29 ms despite low typical costs. No hard 20-ms viewport
slice guarantee is claimed.

Evidence is under `.artifacts/pin_recovery_production/`: `qualified0..2`,
`report/benchmark.md` (all 76 rows), `ordinary0..2`, `foreground_155_final`,
`foreground_321_final`, and `visuals/integrated_finger_planners.blend`.
The inspection file contains measured before/after planner scenes, not solver
results; two obstruction-focused views show FIBER_321's recovered connection.

Checks: 879 unit tests and 237 focused Blender Fiber tests pass. Native compilation,
Python compilation, diff checks, and the 15-line ratchet pass. The full Blender
suite ran 650 tests and reported 13 failures and eight errors, all reproduced
with a HEAD import overlay (no new failing test identities). They concern existing
Blob target setup, skin-worker dependency setup, package import, Muscle precision,
and runtime reload state. It must not be described as fully green. Dependencies
needed by tests were installed into the ignored artifact test-dependency directory,
not into Blender's global Python environment.

## Authored-pin snapping fallback

Regular authored-pin capture now uses `core/vcp/fiber_pin_snapping.py` in both
interactive tools and authoring. It preserves a qualified nearest/raycast payload
exactly. An unsuitable hit triggers the same-owner subdivision-4 / subdivision-8
search with eight seed refinements (32 path samples, 18 bisections) from the
qualified resnapping reference. The fallback never changes the selected SCP or
normal offset and never calls a full planner or Fiber solver.

Qualification requires an exposed owner surface, other-SCP clearance with the
serialization guard, and a usable local exit. Connected owner components are
checked separately so hidden overlap surfaces do not receive an owner exemption.
Local exit sampling uses the ordinary oblique candidates followed, when empty,
by 256 Fibonacci directions at two distances. This only establishes a local exit,
not a complete route. The exact serialized binding is checked before return.

Covered paths: endpoint/touch/loop handle edits, Quick Fiber, mesh/proxy-vertex
creation and touch tools, authoring `anatomy.snap_points`, and unbound authoring
seed snapping. Explicit retained bindings and generic node/Soft Tissue captures
are unchanged. Failed edits restore the old handle/binding; failed selected
vertices cannot be silently omitted. Authoring reports mode, rejection reason,
displacement from the ordinary snap, candidate checks and qualification time;
`max_distance` still limits usable hits.

The snapping layer shares one immutable collider capture per supplied operation
runtime. That runtime must not be retained across geometry edits. Native collision
decisions and owner guards are unchanged; unused planner graph-edge cache writes
and duplicate identical exit queries are omitted. This optimization reproduced
every binding from the unoptimized integration exactly.

Evidence and the reproducible `tools/fiber_pin_snap_qualification.py` harness use
the frozen, already-unioned finger surfaces, then run actual production snapping.
They do not perform Boolean operations or save the source file. The 132 finger
pins qualify and all 76 planner runs succeed. This does not claim that the
unprepared original overlapping surfaces achieve the same result, or that every
solver converges. Evidence: `.artifacts/pin_snap_production/`.

## Maintained regression tools

The old union/resnap experiments, local-tree implementation, one-off render/report
scripts and HEAD-overlay test runner are not production dependencies and have been
removed. The independent analytic box test retains the accepted route and exact
tree/parent hashes in `tests/unit/fixtures/pin_exit_tree_reference.json`; it also
checks every inserted edge with an analytic segment/box intersection test.

Keep these three replay tools for future regression work:

- `fiber_pin_recovery_qualification.py`: frozen requests, ordinary/integrated
  cold/warm planner comparison, optional numerical solve.
- `fiber_pin_recovery_foreground.py`: actual Blender Preview/Recompute flow.
- `fiber_pin_snap_qualification.py`: real authored-pin capture, fallback and
  optional planner validation on the frozen prepared surfaces.

For example, from the repository directory (Blender executable must be on PATH):

```powershell
blender -b --factory-startup --python-exit-code 1 --python tools/fiber_pin_recovery_qualification.py -- --source 'E:/development/WIP_models/whole_skeleton_muscles_20260912/skeleton_muscles.blend' --reference .artifacts/pin_union_all_20260914/qualified --output .artifacts/pin_recovery_retest --fibers FIBER_156 FIBER_321
```

The frozen fixture and historical timing/render outputs remain local evidence,
not bundled production data. The earlier experimental timing table above remains
historical; this maintained harness no longer executes the deleted experiment.

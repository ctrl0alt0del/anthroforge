# Conditional expanded roadmap recovery

Production policy: `conditional-expanded-roadmap-1`. Implemented by the request-local
planner session; no experimental imports, global last-graph capture, or runtime monkeypatches.

## Fixed behavior

DIRECT, SURFACE_BRIDGE, SURFACE_MESH, compatibility, sparse, dense, and normal/oblique
pin exits retain their existing order and numerical rules. After those roadmap attempts
fail, expand the last submitted graph once per authored span. Successful spans are not
replanned. Supported cyclic requests include the closing span.

Restore existing sparse/dense shell coverage, retaining original point indices and links.
Deduplicate only new coordinates at ten decimals, in first-occurrence order. Validate
new points; connect each retained point to the exact 48 nearest neighbors and anchors
0/1, bidirectionally. Distance ties use the original index. Anchor ownership and collision
queries use the existing policy. Search remains the existing bounded 512-attempt native
lazy A*. Shortcutting, exact-count handoff, and final independent validation are unchanged.

Recovery does not repair pins or containment, change clearance, alter SQP, or retry a
safe route that fails exact-count handoff. Solver budget exhaustion never schedules a
new route. A disconnected finite graph is not proof of geometric infeasibility.

## Composition and compatibility

- `planner.py`: compatible synchronous facade and existing numerical route/handoff helpers.
- `planner_session.py`: resumable strategy coordination and native search adapter.
- `planner_preparation.py`: stable candidate preparation and shared-policy validation adapter.
- `planner_search.py`: immutable policies/outcomes and request-local mutable context.

V3 advances the planner between attempts/preparation batches; synchronous V2/V3 callers
drain the same session. Native A* remains atomic, as do existing ordinary candidate
construction operations. This change does not promise a 20 ms maximum slice for them.
Cancellation releases request-local captures and results never bypass the existing
publication coordinator. Warm bypass and propagated attachment-only updates are retained.

The existing ABI 3 backend gains capability `134217728` and `af_roadmap_neighbors`.
The packaged build is `af_fiber_ccd_v3_12.dll`; no helper DLL or new worker pool is used.
Missing capability reports backend unavailable. The slow preparation implementation is
test-only. Planner/engine identities change to prevent reuse of old exact results.

## Acceptance reference and evidence

The accepted source is the COMBINED preparation configuration measured on 2026-09-14:
native exact-neighbor preparation, batched anchor processing, and stable vectorized
deduplication. It preserves the unoptimized RETAIN graph, not an approximate replacement.
Reference graph preparation is independently retained in `tests/roadmap_reference.py`.

Run `tools/fiber_roadmap_qualification.py` with Blender and `--source`, `--output`,
`--repeat`, optionally `--solver --export`. Run three fresh processes, rotating the
paired BASE/REFERENCE/INTEGRATED configurations. Graph audits are outside timing.
BASE is the unchanged ordinary route chain; REFERENCE is unoptimized expanded coverage.

Required recovery fixtures are FIBER_170/173/174 in the supplied whole-skeleton file.
FIBER_128/181 must bypass recovery. FIBER_154/155/156/162/321 are negative controls,
not promised fixes. Match graph hashes, exact points, pins, count, validation, and
non-timing solver diagnostics. Keep source hashes and full raw timing boundaries.

`tools/fiber_roadmap_visualize.py` creates matched renders and inspectable exact-polyline
copies from qualification JSON. `tools/fiber_roadmap_foreground.py` exercises the actual
operator and production timers in foreground Blender without manually draining jobs.

Algorithm basis: [Lazy PRM](https://www.kavrakilab.org/publications/bohlin-kavraki2000path-planning-using.html)
and [C++ exact selection/partial ordering](https://learn.microsoft.com/en-us/cpp/standard-library/algorithm-functions?view=msvc-170).
No SPARS/CTopPRM or CUDA implementation is included.

## Qualification on 2026-09-14

Evidence is in `.artifacts/roadmap_production_20260914/`. `release/` contains three
fresh, rotated, factory-startup Blender runs. `negative/` contains unresolved controls.
`tools/fiber_roadmap_results.py` verifies graph, seed, final-point and non-timing solver
diagnostic parity. The source SHA256 remains
`2991dfa26ee6d3d70a51dfe93b88b75046a9410b624e8b93f2f5c09cee12e0d2`.

Cold numerical begin-to-done medians, milliseconds (not UI latency):

| Fiber | Without recovery | Unoptimized recovery | Integrated recovery |
|---|---:|---:|---:|
| 170 | 589.61 | 574.95 | 496.06 |
| 173 | 353.45 | 588.57 | 494.41 |
| 174 | 423.57 | 556.03 | 479.78 |
| 128 | 135.61 | 133.42 | 136.14 |
| 181 | 248.43 | 249.59 | 247.44 |

The no-recovery results on 170/173/174 use a failed planner's DIRECT fallback, not
the same route. Do not interpret their shorter times on 173/174 as equivalent quality.
Integrated recovery preserves the experimental 49-point, independently validated,
cap-180 results exactly. Controls 128/181 do zero recovery work; unresolved controls
retain their planner failures. `negative_release/` additionally verifies unchanged
final DIRECT-fallback solver points for all five negative controls, cold and warm.
No solver iteration or tolerance change is involved.

Integrated standalone-planner sub-stage medians (nested timings; do not add them to
the complete planner column):

| Fiber | Expanded preparation | Expanded search | Corridor check/shortcut | Complete handoff | Complete planner |
|---|---:|---:|---:|---:|---:|
| 170 | 55.20 ms | 20.62 ms | 1.30 ms | 1.86 ms | 438.22 ms |
| 173 | 49.61 ms | 8.43 ms | 0.72 ms | 1.43 ms | 412.95 ms |
| 174 | 48.00 ms | 8.46 ms | 0.71 ms | 1.50 ms | 416.28 ms |

Standalone planning captures its own snapshot; numerical V3 shares its already-built
world/snapshot with the planner. Their planner time boundaries therefore differ.

The historical 458/461/432 ms observations were not treated as timeless baselines.
The 174 release median is 11.1% above its historical observation. A fresh paired replay
against the frozen accepted experiment, with identical captured requests, gives
528.32/527.23/495.63 ms versus integrated 524.49/527.62/497.31 ms: all within 0.8%.
`fiber_roadmap_reference_replay.py` is test-only, explicitly loads the selected frozen
checkout and optional archived experiment, and is never imported by production.
Its post-capture replay numbers are a separate comparison from the loaded-file runs.

Actual foreground FIBER_170 (`foreground_2/`): Planner Preview 9.61 s, cold Recompute
7.93 s, warm Recompute 4.56 s. These are operator-to-job/downstream-idle observations
in the full visible skeleton scene. Preview changed no persistent points/generation;
each Recompute committed exactly once. Warm Recompute bypassed the planner.
The longest measured foreground planner phase was ordinary preparation, 104.84 ms;
expanded search reached 25.22 ms. Event-loop observation gaps reached 675.2 ms and are
not attributed to a numerical phase. This delivery does not fix those wider UI costs.

859 unit tests pass (6 skipped, 1 expected failure). The focused Blender Fiber suite
passes 233 tests. A complete 646-test Blender run has 13 failures and 8 errors; the
exact same 21 failures/errors reproduce on unmodified HEAD with the same dependencies.
They concern draft-skin/vendor loading, import and Muscle persistence/runtime fixtures,
not new roadmap tests. The whole repository therefore is not claimed fully green.

`previews/` contains matched real Blender renders and exact-polyline inspection copies.
Each inspection file preserves all three solver variants and planner paths in separate
collections; a separate planner copy opens with the recovered seed visible.

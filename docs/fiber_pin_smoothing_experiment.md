# Fiber bridge recovery and hard-pin smoothing experiment

## Status

This is an opt-in V2 experiment layered on V2.4. It is not wired into the
production Fiber runtime and does not change existing saved Fibers. The first
pin-only version rounded corners but did not lower the intended
`skull_muscles_skin.blend/FIBER_1` lifted-planner arch. The current version uses
the planner's `SURFACE_BRIDGE` metadata to establish a safe 2-radius corridor,
then fuses the closer pull and hard-pin smoothing into one second CCD motion.
At a mixed `SURFACE_BRIDGE`/direct hard pin it additionally uses the surface-side
tangent and per-node surface normals, subject to its own CCD and exact validator.
For a high-turn corridor whose many spans all share one owner, it instead builds
one pin-interpolating tangent field and reaches it through a lifted CCD path.

## Targeted lifted-arch result

The actual skull-skin Fiber uses these planner spans:

- edges 0-30: `SURFACE_MESH` on `SCP_1`;
- edges 31-46: `SURFACE_BRIDGE` at 8 times collision radius;
- edges 47-62: `SURFACE_BRIDGE` at 4 times collision radius.

The planner reaches 0.0160 world units from the owner surface. On the actual
bridge indices, V2.4 leaves a maximum distance of 0.007152. The retained
two-stage recovery lowers that to 0.003506, a 51.0% reduction. A direct move to
1.5 times collision radius is blocked, so the first stage moves to 2.0 times
radius; from that feasible state, CCD safely accepts 49.47% of the second move
toward 1.5 times radius. A third 1.25-radius stage was measured and rejected, so
it was removed rather than paying for a collision pass that changes nothing.

Worst/p95/total turning improve from 54.26/28.98/362.64 degrees to
45.97/22.82/331.90 degrees. All four authored pins are bit exact and independent
static validation passes. This materially lowers the arch and rounds its pin
transitions, but it does not claim to reproduce the stored V1 curve exactly.

## Implemented behavior

The experiment preserves V2.4 unless all of these conditions hold:

- the Fiber is open;
- V2.4 selected its light collision path rather than dynamic certificates;
- the first structural step was accepted only partially by CCD;
- the planner metadata contains no `ROADMAP` span;
- the current p95 turn is at least 8 degrees;
- at least one four-node hard-pin neighborhood exceeds 12 degrees.

When active, it first identifies `SURFACE_BRIDGE` spans. Free span nodes move to
2.0 collision radii from the owning surface. The 1.5-radius target is fused with
an amplified arc-length Hermite smoothing proposal, projected into the owner's
tangent plane, and submitted as one second native CCD motion. Strength 3.0
compensates for the approximately half step allowed by CCD. Stronger values
reduced one peak but worsened p95 and total turning. If stage one fails, stage
two is skipped and the cheaper pin-only fallback remains available.
Whole-corridor retraction additionally requires one or two contiguous spans on
one owner and a maximum planner lift of at least four collision radii. Lower
lift spans use only the cheaper hard-pin smoothing pass.

An accepted candidate must reduce the fixed-reference curvature merit while
not increasing maximum, p95, or total turning. CCD validity is mandatory, and
the final points receive the same independent static validation as V2.4. The
dynamic-certificate path, cyclic Fibers, low-p95 isolated corners, and late
V2.4 iterations are delegated unchanged to V2.4.

## Benchmark method

- Blender 5.0.1, Windows x64, current workstation.
- Each solver ran in a separate fresh Blender process.
- Each row contains one route-cold run and eight route-warm runs.
- Collider/request capture was completed before the solver timer.
- Both solvers received the same immutable request and triangle snapshot.
- Source blend files were opened read-only and remained unsaved.

### Exact target: `skull_muscles_skin.blend/FIBER_1`

| Measurement | V2.4 | Bridge-aware | Change |
|---|---:|---:|---:|
| cold solver median, 4 processes | 83.09 ms | 85.00 ms | +2.3% |
| pooled warm p50, 32 runs | 21.90 ms | 23.63 ms | +7.9% |
| pooled warm p95, 32 runs | 26.33 ms | 25.81 ms | -2.0% |
| capture + cold median | 179.41 ms | 180.50 ms | +0.6% |
| maximum bridge distance | 0.007152 | 0.003506 | -51.0% |
| maximum turn | 54.26 deg | 45.97 deg | -15.3% |
| p95 turn | 28.98 deg | 22.82 deg | -21.3% |
| total turn | 362.64 deg | 331.90 deg | -8.5% |
| path length | 0.711198 | 0.708321 | -0.4% |

Four fresh-process replications produced 32 warm samples per solver. The fused
path's 1.73 ms p50 premium is substantially smaller than the unfused version's
6.89 ms. Recovery pair work falls from 459 to 307. Median traced solve/candidate/
CCD times change from 1.423/2.866/14.558 ms to 0.484/0.989/14.124 ms. The new
path additionally spends 2.117 ms in owner-nearest queries; this explains most
of the remaining total difference. Its warm p95 is slightly lower than V2.4,
so the improvement does not add a worse latency tail.

As non-activation controls, `skull_muscles.blend/FIBER_14` and
`skeleton_comb_base.blend/FIBER_1` produced bit-identical coordinates and
metrics. A five-span `skull/FIBER_2` also skips whole-corridor retraction; its
pin-only recovery improved max/p95 turns from 78.24/57.78 to 60.18/50.63 degrees
while measuring 21.09 ms versus V2.4's 28.71 ms in the focused control run.

### Expanded problematic-Fiber qualification

All 24 skull Fibers were first ranked with V2.4. The nine valid high-turn rows
below were then measured in fresh Blender processes with one cold and nine warm
runs per solver. All results independently validated, all authored pins were
bit exact, and source files remained read-only.

| Fiber | Route policy | V2.4 warm ms | guarded warm ms | max turn | p95 turn | Outcome |
|---|---|---:|---:|---:|---:|---|
| FIBER_2 | surface only | 26.48 | 20.16 | 78.24 -> 60.18 | 57.78 -> 50.63 | improved |
| FIBER_3 | surface only | 24.43 | 15.40 | 29.35 -> 28.67 | 17.13 -> 16.62 | improved |
| FIBER_22 | direct/surface | 19.37 | 15.23 | 91.62 -> 88.97 | 10.50 -> 10.17 | improved, low-lift retraction skipped |
| FIBER_10 | includes roadmap | 131.39 | 129.88 | unchanged | unchanged | exact V2.4 output |
| FIBER_9 | includes roadmap | 96.61 | 97.20 | unchanged | unchanged | exact V2.4 output |
| FIBER_4 | includes roadmap | 76.62 | 73.65 | unchanged | unchanged | exact V2.4 output |
| FIBER_25 | includes roadmap | 134.40 | 136.13 | unchanged | unchanged | exact V2.4 output |
| FIBER_23 | isolated peak | 15.14 | 15.46 | unchanged | unchanged | activation skipped |
| FIBER_19 | no eligible window | 14.57 | 14.56 | unchanged | unchanged | activation skipped |

The unguarded experiment had materially regressed the roadmap rows: maximum
turn rose from 72.07 to 102.67 degrees on FIBER_10, 37.96 to 78.83 degrees on
FIBER_9, and 29.54 to 82.82 degrees on FIBER_25. Those paths need the complete
multi-trial V2.4 collision solve; terminating after the first partial step is
not a valid optimization for them. The metadata guard now delegates them to
V2.4, producing a numeric maximum point delta of exactly zero.

### Surface-boundary tangent correction

The earlier FIBER_22 result was not satisfactory. Its batch proposal coupled
two hard-pin windows and projected every moved node against the normal sampled
at one pin. CCD therefore limited the whole batch at edge 39 beside the other
window, accepting only 8.52% of the proposed motion. More smoothing could not
repair that geometric error.

The retained correction activates only where exactly one adjacent planner span
is `SURFACE_BRIDGE`, its owner matches the hard pin, and the local turn exceeds
45 degrees. It derives the shared tangent from the surface-side span, projects
each free node against that node's own nearest owner-surface normal, restores
every pin, and performs native CCD plus exact static validation. Before CCD it
rejects proposals that do not reduce the worst turn by at least 5 degrees and
10%, keep p95 within 2 degrees, and avoid increasing total turning.

On `skull/FIBER_22` the full correction is collision-safe. Maximum/p95/total
turn change from 91.62/10.50/204.79 degrees to 57.71/11.01/158.90 degrees;
curvature merit changes from 813.74 to 242.88. All four pins are bit exact.
Ten-run focused medians were 19.03 ms for V2.4 and 17.89 ms for the corrected
path. Continuing ordinary V2.4 refinement afterward cost 28.46 ms, improved
the maximum turn by only another 0.01 degree, and still terminated `BLOCKED`;
that continuation was rejected.

Every open Fiber in both skull files was audited with one shared immutable
collider snapshot. All 12 independently validated in each file. Four retained
quality changes (FIBER_1, FIBER_2, FIBER_3, and FIBER_22); only FIBER_22 accepted
the new boundary branch. `skeleton_comb_base/FIBER_1` remained exactly V2.4 and
independently valid. FIBER_2 is now handled earlier by the whole-span branch
described below, so it does not pay for an unsuitable local boundary proposal.

### Whole-span pin interpolation

The preceding local four-node windows were not sufficient for `skull/FIBER_2`.
Its six authored pins divide the curve into five lifted surface spans. V2.4
left its worst/p95/total turning at 78.24/57.78/654.59 degrees. The stored V1
shape measures 45.02/20.11/252.91 degrees, but it fails the current independent
clearance validator, so copying its smoother coordinates is not an acceptable
solution.

The retained same-owner surface branch constructs one uniform-parameter cubic
Hermite field through every hard pin, using one shared tangent on both sides of
each pin. It then projects only the displacement into each node's local owner
tangent plane. A direct interpolation between the valid V2.4 curve and the
valid target sweeps through the owner surface, so the transition uses two CCD
segments with a one-radius sinusoidal outward lift. Both segments must be full;
partial or uncertain motion is rejected. Hard pins are restored at every
waypoint, and the final candidate receives independent static validation.

The branch is deliberately narrow: at least four pins, one owner for every
anchor and planner span, every span marked `SURFACE_BRIDGE`, and a V2.4 p95 turn
of at least 30 degrees. It uses tangent strength 1.25. On the production Fiber,
worst/p95/total turning becomes 32.52/21.92/397.71 degrees and curvature merit
falls from 1398.92 to 197.37. Every hard pin is bit exact and validation passes.
Ten-run warm medians are 27.01 ms for V2.4 and 31.52 ms for the corrected path
(+4.52 ms, +16.7%); the corrected route-cold run is 62.26 ms versus 86.20 ms
because it avoids V2.4's later blocked trials.

All 12 open Fibers in each skull file still validate; only FIBER_2 activates
this branch. The four previously improved Fibers remain the only changed rows.
The skeleton control remains bit-identical to V2.4. Anatomical comparison files
are in `artifacts/fiber_pin_smoothing/anatomical_global_balanced_skull_FIBER_2/`
and `artifacts/fiber_pin_smoothing/anatomical_global_balanced_skull_FIBER_2.blend`.
Orange is stored V1, magenta is V2.4, green is the corrected path, yellow marks
hard pins, red is the shared attachment owner, and gray surfaces are unrelated
colliders. The front/side/top views show the shape difference. Independent edge
validation—not the translucent overview—is the evidence that corrected output
is safe and the stored path is not; the stored path's failure occurs between
sampled nodes and is not reliably visible in a whole-Fiber render.

The unambiguous diagnostic set is in
`artifacts/fiber_pin_smoothing/anatomical_clearance_skull_FIBER_2/`, with an
editable copy at `artifacts/fiber_pin_smoothing/anatomical_clearance_skull_FIBER_2.blend`.
In its close views, the thin green curve is the centerline, the translucent blue
tube is exactly one collision radius, and each short green connector terminates
at the native nearest-surface point. Cameras look across the local surface
normal so the gap cannot collapse in projection. `clearance_profile.png` plots
signed node distance in radius units; its yellow verticals are hard pins, where
zero-distance owner contact is intentional. This node profile complements but
does not replace full edge validation, which catches between-node crossings.
`clearance_validation_sheet.png` combines the anatomical comparison, radius
shell, three true-scale profile closeups, and normalized clearance plot into one
labeled review image.

### Superseded pin-only baseline

The following matrix records the earlier pin-only experiment. It is retained to
show why low timings and better turn metrics alone were insufficient: that
version never lowered the target bridge and is not the current algorithm.

| Case | V2.4 cold ms | New cold ms | V2.4 warm median ms | New warm median ms | max turn | p95 turn | total turn | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| skull/FIBER_1 | 80.66 | 73.89 | 20.57 | 15.74 | 54.3 -> 47.9 | 29.0 -> 22.6 | 362.6 -> 338.6 | active, valid |
| skull/FIBER_2 | 86.29 | 78.09 | 26.62 | 19.86 | 78.2 -> 60.2 | 57.8 -> 50.6 | 654.6 -> 589.1 | active, valid |
| skull/FIBER_3 | 69.56 | 61.54 | 24.73 | 15.04 | 29.4 -> 28.7 | 17.1 -> 16.6 | 179.4 -> 175.1 | active, valid |
| skull/FIBER_19 | 31.65 | 28.91 | 14.02 | 14.12 | unchanged | unchanged | unchanged | skipped, exact V2.4 points |
| skull/FIBER_22 | 31.16 | 28.18 | 18.67 | 15.25 | 91.6 -> 89.0 | 10.5 -> 10.2 | 204.8 -> 198.9 | active, valid |
| skull/FIBER_23 | 23.16 | 24.95 | 14.85 | 15.72 | unchanged | unchanged | unchanged | low-p95 skip, exact V2.4 points |
| skull-skin/FIBER_1 | 94.28 | 75.63 | 21.52 | 15.72 | 54.3 -> 47.9 | 29.0 -> 22.6 | 362.6 -> 338.6 | active, valid |
| skeleton/FIBER_1 | 160.00 | 161.21 | 136.61 | 141.49 | unchanged | unchanged | unchanged | dynamic-path skip, exact V2.4 points |

Across the eight rows, the median change was -9.08% cold and -20.91% warm.
The two unchanged expensive/unsuitable paths show small process-level overhead:
FIBER_23 was +0.88 ms warm and skeleton/FIBER_1 was +4.88 ms warm. They produce
bit-identical V2.4 coordinates.

For the primary skull/FIBER_2 case, V2.4 used three trials while the experiment
used one structural trial plus one smoothing motion. Candidate construction fell
from 2.67 to 1.61 ms, structural solve time from 1.48 to 0.45 ms, and aggregate
CCD time from 19.69 to 11.44 ms. The smoothing portion itself cost 6.49 ms:
0.73 ms geometry, 0.23 ms owner-nearest queries, and 5.20 ms CCD over 247
candidate pairs. Independent final validation remained enabled.

Fresh-process request capture for skull/FIBER_2 measured 98.42 ms in the V2.4
run and 94.52 ms in the experiment run. Cold capture plus solve was therefore
182.56 versus 174.82 ms. Capture is shared infrastructure and is not improved by
this experiment.

## Visual assessment

- `artifacts/fiber_pin_smoothing/visual_FIBER_2.png`
- `artifacts/fiber_pin_smoothing/visual_FIBER_2.blend`
- `artifacts/fiber_pin_smoothing/visual_FIBER_1.png`
- `artifacts/fiber_pin_smoothing/visual_FIBER_1.blend`
- `artifacts/fiber_pin_smoothing/span_retraction_two_stage_skin_FIBER_1.png`
- `artifacts/fiber_pin_smoothing/span_retraction_two_stage_skin_FIBER_1.blend`
- `artifacts/fiber_pin_smoothing/final_bridge_recovery_skin_FIBER_1.png`
- `artifacts/fiber_pin_smoothing/final_bridge_recovery_skin_FIBER_1.blend`
- `artifacts/fiber_pin_smoothing/final_bridge_profile_skin_FIBER_1.png`
- `artifacts/fiber_pin_smoothing/final_bridge_profile_skin_FIBER_1.blend`
- `artifacts/fiber_pin_smoothing/problem_skull_FIBER_2.png`
- `artifacts/fiber_pin_smoothing/problem_skull_FIBER_3.png`
- `artifacts/fiber_pin_smoothing/problem_skull_FIBER_22.png`
- `artifacts/fiber_pin_smoothing/guarded_skull_FIBER_9.png`
- `artifacts/fiber_pin_smoothing/guarded_skull_FIBER_10.png`
- `artifacts/fiber_pin_smoothing/guarded_skull_FIBER_25.png`
- `artifacts/fiber_pin_smoothing/anatomical_tangent_skull_FIBER_22/`
- `artifacts/fiber_pin_smoothing/anatomical_tangent_skull_FIBER_22.blend`
- `artifacts/fiber_pin_smoothing/anatomical_tangent_skull_FIBER_2/`
- `artifacts/fiber_pin_smoothing/anatomical_tangent_skull_FIBER_2.blend`

The anatomical overlays retain actual world coordinates and show front, side,
top, and local-normal views. Attachment-owner SCPs have distinct translucent
colors, unrelated colliders are gray, pins are yellow, V2.4 is magenta, and the
guarded result is green. FIBER_22 rounds the surface-to-direct transition on the
same legal side of SCP_6. The whole-corridor branch now materially corrects
FIBER_2, while the radius-shell closeups make its placement directly readable.
The experiment remains opt-in until equivalent production-runtime publication,
cancellation, and interactive scheduling behavior is qualified.

## Reproducibility

Input SHA-256 values during the run:

- `skull_muscles.blend`: `A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06`
- `skull_muscles_skin.blend`: `2EE614CAC26E65580322013DD7A80D6AF6360D49F26CDB2CEB0D0E9A768BFA96`
- `skeleton_comb_base.blend`: `419029BA2C345F07008F8EB43ABF1DB4599C393692E77FE684CB13CC7560BD42`

Numerical and controller coverage is in
`tests/unit/test_fiber_pin_smoothing_geometry.py` and
`tests/unit/test_fiber_pin_smoothing_solver.py`. The final complete unit suite
passed 503 tests with six native-binary skips and one pre-existing expected
failure. The dependency bundle was loaded outside the repository so the
function-size ratchet inspected addon code only.

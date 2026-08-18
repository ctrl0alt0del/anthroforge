# Fiber V2.5 Branch-2 Experiment

## Scope

V2.5-branch2 is an isolated experiment on top of V2.4. It does not replace V2.4
or change the add-on rollout flag. Its purpose is to test whether solver policy
can remove artifacts introduced by planner branch 2 without running another
planner or weakening collision validation.

Planner branch 2 is the local lifted surface bridge. It joins two anchors on the
same owner surface by lifting a short straight interpolation along interpolated
surface normals until the segment sequence is collision-clear. It is fast and
topology-independent, but exact hard pins can leave very short lift/return edges
and sharp corners in the exact-count reference.

## Production fixture

The selected case is `skull_muscles.blend / FIBER_2`. Every one of its five
anchor-to-anchor spans selects branch 2. The exact metadata is:

| First edge | Edge count | Branch | Owner | Lift factor |
|---:|---:|---|---|---:|
| 0 | 10 | `SURFACE_BRIDGE` | `SCP_1` | 1.25 |
| 10 | 8 | `SURFACE_BRIDGE` | `SCP_1` | 1.25 |
| 18 | 11 | `SURFACE_BRIDGE` | `SCP_1` | 4.0 |
| 29 | 11 | `SURFACE_BRIDGE` | `SCP_1` | 2.5 |
| 40 | 23 | `SURFACE_BRIDGE` | `SCP_1` | 8.0 |

The planner reference measures a 180 degree maximum turn, 118.1 degree p95
turn, and 1306.1 degrees total turn. V2.4 reduces those values, but visible
pin-adjacent corners remain: 78.2 degree maximum, 57.8 degree p95, and 654.6
degrees total.

## Parameter investigation

The first sweep tested 48 combinations of proximal, length, and curvature
weights on a frozen planner route. Weight changes alone were ineffective: the
best maximum turn was still 78.2 degrees. The reason is that V2.4's surface
candidate independently retracts every node to the owner surface, restoring much
of the normal-direction artifact after the structural solve.

The second investigation tested a tangential shell coordinator. It:

1. runs the existing O(N) structural solve;
2. decomposes structural displacement into surface-normal and tangent parts;
3. removes the normal displacement;
4. applies the tangent displacement plus one controlled clearance-shell update;
5. restores exact hard pins;
6. uses the unchanged merit, CCD acceptance, and independent final validator.

The selected all-branch-2 configuration is:

- proximal weight `0.01`;
- length weight scale `4.0`;
- curvature weight scale `0.25`;
- shell distance `3.0 * collision_radius`;
- tangent trust `1.0`.

The scales preserve the user's relative length and curvature controls. The
stronger weights are enabled only when every planner span is branch 2. Mixed
routes keep V2.4 structural weights and apply the tangential shell update only
to exact node ranges tagged `SURFACE_BRIDGE`.

## Planner metadata

`V2PlannerResult.spans` now records one `V2PlannerSpan` per authored
anchor-to-anchor segment after exact-count allocation:

- `first_edge` and `edge_count` identify its exact output range;
- `branch` is `DIRECT`, `SURFACE_BRIDGE`, `SURFACE_MESH`, or `ROADMAP`;
- `owner_id` identifies the surface owner when applicable;
- `lift_factor` records the signed branch-2 lift selected by the planner.
- `start_anchor` and `end_anchor` identify the authored anchors without
  reclassifying geometry; open and cyclic spans retain different end rules.

The data is produced when the planner selects the route, survives exact route
cache replay and safe preview reuse, and is consumed directly by V2.5. No
geometric post-classification is used.

## Runtime policy

The first accepted proposal is always the existing V2.4 proposal. This is the
important acquisition step: it removes the large planner lift without replacing
the already-qualified shape behavior.

After acquisition, only exact node ranges tagged `SURFACE_BRIDGE` receive the
stronger tangential smoothing. An adjacent `SURFACE_MESH` range on the same
continuous surface may participate in the surface update, but it is not counted
as a branch-2 range and does not independently activate the policy. Direct and
roadmap ranges keep their normal structural update.

The controller measures turning only inside tagged ranges after acquisition.
Backtracking recovery is enabled when the remaining maximum turn is at least
70 degrees or the range-local p95 is at least 35 degrees. Cleaner ranges try
only the full update and stop if it is not useful. This prevents the controller
from degrading `FIBER_3` and `FIBER_19`, while retaining recovery for the
visibly kinked `FIBER_2` route.

Every attempted motion uses the existing native CCD. A full safe proposal is
preferred. Only an activated sharp range may test smaller prefixes of that same
CCD-certified motion. Accepted prefixes must strictly reduce the structural
merit; hard pins are restored exactly. A safe candidate with no decreasing
prefix terminates as `STALLED`, not `BLOCKED`, because collision did not block
the motion.

## Real Blender results

All rows use Blender 5.0.1, the read-only production file, the packaged native
collision backend, an exact V2.4/V2.5 route-cache warm comparison, and independent
final validation. Timings are indicative eight-warm-run medians from one process.

| Fiber | Branch-2 spans | V2.4 ms | V2.5 ms | Max turn 2.4 -> 2.5 | P95 turn 2.4 -> 2.5 | Total turn 2.4 -> 2.5 |
|---|---:|---:|---:|---:|---:|---:|
| FIBER_2 | 5 | 30.4 | 34.6 | 78.2 -> 53.2 | 57.8 -> 44.5 | 654.6 -> 539.8 |
| FIBER_1 | 2 | 21.4 | 21.7 | 54.3 -> 50.6 | 29.0 -> 18.4 | 362.6 -> 348.2 |
| FIBER_3 | 3 | 25.9 | 16.8 | 29.4 -> 29.4 | 17.1 -> 17.1 | 179.4 -> 179.6 |
| FIBER_19 | 3 | 13.7 | 14.9 | 56.6 -> 56.6 | 28.2 -> 28.2 | 324.7 -> 324.7 |
| FIBER_22 | 1 | 18.9 | 14.7 | 91.6 -> 91.0 | 10.5 -> 10.5 | 204.8 -> 203.8 |
| FIBER_23 | 1 | 15.6 | 16.4 | 98.0 -> 80.3 | 4.2 -> 10.1 | 211.5 -> 195.6 |

Every V2.5 result in this set passes independent static validation and preserves
all authored pins exactly. V2.5 is not uniformly better on every metric: FIBER_3
changes negligibly, and FIBER_23 trades a lower worst corner and total turn for a
higher p95. That is why this remains an experiment rather than a rollout change.

For the target FIBER_2, stored V1 measures 45.0 degree maximum and 20.1 degree
p95. V2.5 materially improves V2.4 but does not yet match the stored V1 shape.

## Visual and reproducibility artifacts

- `artifacts/fiber_v25_branch2/skull_f2_v25_comparison.png`
- `artifacts/fiber_v25_branch2/skull_f2_v25_review.blend`
- `artifacts/fiber_v25_branch2/skull_f2_v25_actual.json`
- `artifacts/fiber_v25_branch2/qualified_fiber_2.png`
- `artifacts/fiber_v25_branch2/qualified_fiber_2_review.blend`
- `artifacts/fiber_v25_branch2/qualified_fiber_*.json`
- `artifacts/fiber_v25_branch2/skull_f2_controller_sweep_targeted.json`

The comparison render lifts all displayed curves by the same view-space amount
to prevent the translucent collision mesh from hiding them. The point data in
the JSON and review blend remains the exact solver output.

The source blend remained byte-identical with SHA-256
`A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06`.

## Decision

The implementation proves that planner provenance can improve branch-2 artifacts
with O(N) coordination and no extra planning pass. The revised acquisition rule
also prevents the broad regressions caused by applying a new fixed directional
objective from the raw planner reference. It remains opt-in: the target improves
materially but still does not match the stored V1 p95, and `FIBER_23` trades a
lower worst corner for a higher p95. Those are visual-acceptance gaps, not
collision-validation failures.

The implementation follows the local/global separation used by Projective
Dynamics and the obstacle/regularization balance discussed by CHOMP, while all
accepted motion remains subject to the existing native CCD and independent
static validation.

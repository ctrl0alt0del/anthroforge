# Fiber V2 Package 6 — Contact-Space Trust Steps and Certified CCD Filtering

## Status and purpose

Package 6 is an isolated V2 experiment built on Package 5.1. It does not replace
V1, alter saved Fibers, publish runtime output, or enable V2 by default.

Implementation and qualification are complete. The experiment passed its dense
CCD-filtering hypothesis but failed general latency and convergence gates; see
[`fiber_v2_package6_results.md`](fiber_v2_package6_results.md). It remains
isolated and is not a rollout candidate.

Package 5.1 made collision processing faster, but it did not remove the dominant
workload on `skeleton_comb_base.blend/FIBER_1`:

| Measurement | Package 5 | Package 5.1 |
|---|---:|---:|
| Median total | 533.97 ms | 325.08 ms |
| CCD | 328.83 ms | 251.14 ms |
| CCD candidate pairs | 13,429 | 11,532 |
| CCD tested pairs | 13,354 | 11,405 |
| Accepted/rejected trials | 7/1 | 6/1 |
| Terminal state | `BLOCKED` | `BLOCKED` |

The structural solve itself takes about 4 ms. The bottleneck is the sequence of
large global proposals, not matrix factorization. A long roadmap is repeatedly
pulled toward a shorter path through the rib field. Package 5.1 then certifies
four curved waypoint segments for active contacts, but nearly every broad-phase
pair still reaches native narrow-phase CCD.

Package 6 tests one combined hypothesis:

> A collision-tangent, adaptively bounded proposal will preserve the planner's
> collision-free homotopy while generating much smaller swept regions; exact
> distance certificates can then reject far pairs before narrow-phase CCD.

This package deliberately precedes adaptive convergence and Anderson
acceleration. Iteration policy must not hide a blocked or poorly defined base
map.

## Preserved contracts

- The Package 4.3 planner reference `q` remains fixed throughout a solve.
- Authored endpoint and touch pins are eliminated exactly.
- Length, curvature, fidelity, and contact weights are unchanged.
- Planner, contact projection, CCD, and final validation use one immutable
  collider snapshot and one owner-contact policy.
- Every accepted movement starts from a valid curve and is certified by the
  native CCD backend.
- Independent final node/edge clearance validation remains mandatory.
- Package 5 and Package 5.1 remain callable as comparison references.

The new entry point is additive:

```python
solve_package6(request, snapshot=None, contact_weight=1000.0)
```

## Package 6 algorithm

### 1. Fixed structural proposal

Compute the existing local/global proposal `y = G(x; q)` with the fixed planner
reference. Package 6 does not replace `q` with the current iterate and does not
change the banded structural system.

### 2. Contact-space direction projection

Form `d = y - x`. For each node or edge with an exact active contact:

- remove the inward component of `d` along the contact normal;
- preserve the tangential component;
- add only the minimum outward correction required to maintain clearance;
- blend normals deterministically where several contacts meet;
- restore authored pins exactly after projection.

This creates a direction that follows an obstacle instead of proposing a chord
through it and relying on CCD to reduce the chord almost to zero.

### 3. Adaptive trust bound

Apply a solve-wide trust radius `delta` to the projected direction before CCD.
The bound is measured in world units and limits the maximum displacement of any
free Fiber node.

Initial radius:

```text
delta = min(2 * median_edge_length(q), 8 * collision_radius)
```

Update policy:

- full safe step with good merit agreement: `delta *= 1.5`;
- CCD fraction below `0.25`: `delta *= 0.5`;
- rejected merit or changed contact set: keep or halve `delta`;
- clamp to `[0.25 * collision_radius, 4 * median_edge_length(q)]`;
- reset to the initial value after a replan or level change.

The trust bound is a globalization mechanism, not an extra shape energy. A
result may report convergence only after the unclipped base proposal also
satisfies the fixed-point and stationarity tolerances.

### 4. One motion path per trial

Package 6 removes Package 5.1's unconditional four-waypoint CCD path. Each trial
submits one contact-tangent, trust-limited linear movement to CCD. If its safe
fraction is near zero, Package 6 shrinks the trust radius and rebuilds the
contact-tangent direction on the next trial rather than certifying four more
segments of the same globally unsuitable movement.

At most one tangent-recovery retry is allowed for a newly changed contact set.
There is no hidden inner retry loop.

### 5. Conservative distance certificates

Maintain solve-local certificates keyed by `(Fiber edge, collider triangle,
collider generation)`.

For a pair with exact current separation `distance` and maximum endpoint motion
`motion`, skip narrow-phase CCD only when:

```text
distance - requested_clearance - numeric_slack > motion
```

The distance between a moving segment and a fixed triangle cannot decrease by
more than the segment's maximum endpoint displacement. The certificate is
therefore a conservative exclusion, not a heuristic.

Certificate rules:

- new or invalidated broad-phase pairs receive an exact native distance query;
- uncertain, degenerate, contained, owner-boundary, or stale-generation pairs
  always go to exact CCD;
- certificates survive accepted trials only while their recorded lower bound
  remains valid after subtracting accumulated motion;
- collider generation, replan, pin movement, or topology change clears affected
  certificates;
- final validation never trusts a motion certificate.

The native backend should fuse certificate classification and CCD of ambiguous
pairs in one batch. Python must not loop over individual pairs.

### 6. Acceptance and termination

Acceptance is lexicographic:

1. pins remain exact;
2. CCD reports a valid, uncertainty-free movement;
3. feasibility is not worse;
4. the existing Package 5 merit is nonincreasing.

Package 6 terminates as follows:

- `CONVERGED`: unclipped base map and all residual gates pass;
- `BLOCKED`: minimum trust radius plus two exact zero-step CCD results with an
  unchanged contact set;
- `STALLED`: eight accepted trust steps produce no meaningful merit or residual
  reduction;
- `NO_FEASIBLE_PATH`: one bounded replan cannot produce a valid exact-count
  reference;
- `UNSAFE_OUTPUT`: nonfinite or independently invalid final candidate;
- `BUDGET_EXHAUSTED`: accepted-step cap ends while progress continues;
- `BACKEND_UNAVAILABLE`: required native distance or CCD operation is absent.

No `BLOCKED`, `STALLED`, or budget-exhausted result may be called converged.

## Diagnostics

Package 6 records, per solve and per trial:

- structural proposal displacement;
- projected displacement and clipped-node count;
- trust radius before and after the trial;
- contact count and contact-set changes;
- broad-phase pairs;
- certificate hits, refreshes, and rejected pairs;
- exact CCD pairs and interval count;
- CCD fraction and limiting edge/triangle owner;
- accepted/rejected trials and merit;
- fixed-point, stationarity, pin, node-clearance, and edge-clearance residuals;
- exact reason for trust shrink, replan, or termination.

The trace must make `total tested pairs` auditable. A lower per-trial count is not
sufficient if Package 6 merely creates many more trials.

## Experiment and attribution

Package 6 is one implementation with diagnostic switches used only for
attribution:

1. Package 5.1 reference;
2. trust/contact-space proposal with full CCD;
3. certificates with the Package 5.1 proposal;
4. combined Package 6.

All variants use the same request, planner reference, native backend, final
validator, process state, and output count. Results are recorded in randomized
order after equal warmups. V1 comparisons normalize `use_surface_routing` and
all other route-policy fields explicitly.

## Mandatory real-Blender qualification

Read-only benchmarks:

- `skull_muscles.blend/FIBER_1`;
- `skull_muscles.blend/FIBER_14`;
- `skull_muscles_skin.blend/FIBER_1`;
- `skeleton_comb_base.blend/FIBER_1` and `FIBER_2`.

For every fixture, produce:

- at least seven warmed repetitions in fresh Blender processes;
- phase and pair-count JSON;
- a left-to-right Blender render: V1, planner reference, Package 5.1, Package 6;
- a temporary `.blend` comparison file for direct viewport inspection;
- path length, curvature, pin error, clearance, and termination tables;
- unchanged SHA-256 for every supplied source file.

## Gates

Correctness:

- zero certificate false exclusions against full native CCD and the independent
  reference suite;
- every returned curve passes independent node and edge clearance validation;
- exact pins satisfy the existing scene-scale tolerance;
- cold and warm Package 6 runs are deterministic;
- trust limiting cannot change the converged fixed point;
- Package 6 never crosses to a different obstacle homotopy from the validated
  planner reference.

Skeleton performance target:

- exact CCD tested pairs at least 4x below Package 5.1 (`<= 2,851` for the
  recorded `FIBER_1` fixture);
- CCD phase below 100 ms;
- total median below 200 ms;
- no internal trial performs four unconditional waypoint sweeps;
- fixed-work scaling remains below 2.4x from 256 to 512 nodes.

Regression limits:

- skull Fiber medians no more than 10% slower than Package 5.1;
- planner time and output are unchanged;
- no loss of requested clearance or path-quality metrics;
- a zero safe step cannot trigger visible retry oscillation.

Behavioral target:

- the demonstrably feasible skeleton Fibers should no longer terminate
  `BLOCKED` solely because a global structural chord points through a rib;
- if they remain blocked, diagnostics must identify the limiting edge, collider,
  trust radius, and exact CCD pair so Package 7 is not designed from aggregate
  timing alone.

## Deferred packages

- Package 7: adaptive levels, normalized convergence, progress windows, and
  best-validated preview publication.
- Package 8: safeguarded Anderson acceleration after the unaccelerated map is
  correct and stable.
- Package 9: pure-data resumable engine and fair shared multi-Fiber scheduling.
- Package 10: production qualification, migration, packaging, and rollout.

## Research basis

- IPC maintains feasibility during optimization with a contact-aware line search
  and conservative collision bounds:
  <https://ipc-sim.github.io/file/IPC-paper-fullRes.pdf>
- Penetration-free Projective Dynamics shows that merely truncating a global PD
  proposal with CCD can cause sticking, supporting a contact-aware proposal
  rather than repeated CCD pruning:
  <https://www.math.ucla.edu/multiples/publication/lan2022pdipc.pdf>
- Safeguarded Anderson acceleration is intentionally deferred until the base
  local/global map is correct:
  <https://arxiv.org/abs/1805.05715>

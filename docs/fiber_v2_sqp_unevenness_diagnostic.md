# Fiber V2 span-SQP unevenness diagnostic

Date: 2026-08-26

## Scope

This report diagnoses the circled bump in `fiber_sphere.blend/FIBER_2` using the corrected
span-SQP experiment. It changes no solve policy. The new trace is opt-in through
`diagnostic_trace=True`; ordinary experiment calls do not retain iteration geometry or
compute its diagnostic arrays.

Source SHA-256 stayed unchanged:

`D454901E8CE3031FA9E4401EEEF593BDB3B00AA705FBD3FC69880F2E4D936EC9`

The trace records every `SEED`, `PROPOSE`, `CCD`, `TRIAL`, `DECISION`, and `FINISH` event,
including points, per-node turns and step lengths, segment lengths, reference distances,
all objective terms, structural/contact/total gradients, gradient opposition, contact
identity and lifetime, multipliers, complementarity, SQP normal/tangent work, trust
radius, conditioning, CCD limiting pairs and pair counts, feasibility, residuals, and
the exact rejection reason.

## Reproduction

- Fiber nodes: 64.
- Hard-anchor spans: 4.
- Circled region: span 0, nodes 9 and 10; the worst isolated turn is global node 10.
- Aggregate result: validated `CONVERGED`, 36 accepted and 34 rejected steps.
- Span 0: 11 accepted and 19 rejected proposals.
- Untraced median: 174.043 ms over five fresh-cache runs.
- Full diagnostic trace: 227.826 ms, or 30.90% diagnostic overhead.
- A 240-step-cap replay produced exactly the same points (`max point delta = 0`), with
  the same 36 accepted and 34 rejected steps.

The trace overhead is intentionally excluded from normal solving. It is acceptable for
this investigation because it serializes full geometry and gradients at every phase.

## Exact iteration where the uneven region appears

Before the bump, accepted proposal 12 leaves:

- node 9 turn: 4.65 degrees;
- node 10 turn: 2.71 degrees.

Proposals 13–16 repeatedly discover new collision constraints on collider `SCP_2:1`.
Proposal 17 is the first accepted state with the visible uneven region:

- node 9 turn jumps to 23.68 degrees;
- node 10 turn jumps to 18.86 degrees;
- the proposal is solved with active CCD-injected constraints on edges 8 and 9;
- their SQP duals are 62.12 and 191.40;
- the trust radius entering the proposal is 0.4335 world units;
- CCD certifies the constrained proposal at a full step, so it is safely accepted.

The bump is therefore created in the `PROPOSE` phase of proposal 17 by the active
collision constraints. It is not introduced by publication, resampling, final
validation, or the span join. Node 10 is two nodes before the hard midpoint at node 12.

## Why later smoothing does not remove it

Immediately after proposal 17, the structural optimizer repeatedly proposes a much
smoother chord. CCD correctly rejects that chord because it moves through the same
obstacle face:

| Proposal | Current node-10 turn | Proposed turn | CCD safe fraction | Contact normal motion | Tangential motion |
|---:|---:|---:|---:|---:|---:|
| 18 | 18.86° | 1.32° | 0.002661 | -0.66 | 0.07 |
| 20 | 18.18° | 1.35° | 0.003655 | -0.59 | 0.02 |
| 22 | 21.11° | 1.27° | 0.002678 | -0.59 | 0.05 |

Negative normal motion means movement into the obstacle. All three attempts are blocked
by Fiber edge 9 against global face 962, which maps to `SCP_2:1`, local triangle 2. The
proposals are not grazing numerical false positives: 89–97% of the contact-point motion
is inward, and CCD allows only 0.27–0.37% of the requested movement.

The current loop responds by rejecting the entire chord, injecting one linear limiting
constraint, and solving again. That next solve is safe, but it restores much of the bend.
After acceptance, the swept limiter has no matching static contact and is correctly
retired. The following unconstrained structural proposal points inward again. This is the
repeated pattern visible in proposals 18–27.

## Why the solver finally declares convergence

The final worst turn is node 10:

- turn: 22.709°;
- local turn excess: 9.722°;
- node 9 turn: 18.909°;
- curvature energy decreases from 169.419 at the first uneven state to 163.760, so the
  curvature objective is active and does smooth what the current constraints permit.

The final state has two contacts that both act almost exactly at shared node 10:

- edge 9, factor 0.997899, multiplier 258.311;
- edge 10, factor 0.001975, multiplier 58.711;
- both refer to `SCP_2:1`, triangle 2;
- their contact normals differ by 25.073 degrees.

At node 10, the structural gradient norm is 311.840 and the contact gradient norm is
311.832. Their cosine is -0.999999998, leaving a total norm of only 0.02097. At node 9,
the corresponding values are 0.53397, 0.54284, -0.999999997, and 0.00887. The normalized
final stationarity residual is `3.2115e-8`; the fixed-point residual is `1.7458e-6`.

So the solver is not stopping because it ran out of iterations. It found a stationary
point of its current linearized contact model: collision forces almost perfectly cancel
the length/curvature forces. Numerically, `CONVERGED` is consistent. Geometrically, this
local contact equilibrium is not the desired tight surface-following route.

## What is missing

The missing capability is a feasible surface-following step, not a larger cap or a
stronger rejection loop.

1. When the smooth chord hits a surface, the remaining movement must be redirected into
   the local feasible tangent cone and relinearized along the surface. The current code
   only chooses between the inward chord and a new linear normal constraint.
2. Contacts on adjacent Fiber edges whose factors are almost 1 and 0 must be recognized
   as one shared-node contact manifold. They must retain every safety normal as a cone,
   while solving one coordinated tangential motion for the node. Treating them as two
   unrelated edge forces can pinch the node and remove useful tangent freedom.
3. A swept limiting pair needs proposal-local continuity while constructing the curved
   feasible step. It must not become a persistent fake collision, but it also must not be
   forgotten before the solver has formed a surface-following replacement direction.
4. Every redirected substep must still pass native CCD. Independent final validation
   remains an assertion, not repair.

A production fix should therefore advance to the certified time of impact, build the
shared-node contact manifold, project the remaining objective displacement into its
feasible tangent cone, requery contacts, and repeat in bounded microsteps. This directly
targets the observed failure while preserving the collision-safe invariant.

## Ruled out by this trace

- More iterations: cap 60 and cap 240 are point-identical.
- A false collider: every blocked smooth attempt identifies the same real SCP face.
- A broken curvature term: curvature energy falls and its gradient is large.
- The authored hard midpoint: the maximum bump is internal to span 0.
- Planner publication or final validation: the uneven turn first appears in SQP proposal
  17 and is already present before commit.
- A generic `STALLED` threshold: the current result reaches the stated numerical
  stationarity tolerances.

## Artifacts

- Raw full trace: `.artifacts/fiber_v2_dynamic_step/sphere_f2_sqp_iteration_trace.json`
- High-cap trace: `.artifacts/fiber_v2_dynamic_step/sphere_f2_sqp_iteration_trace_cap240.json`
- Node-9 analysis: `.artifacts/fiber_v2_dynamic_step/sphere_f2_sqp_iteration_analysis.json`
- Node-10 analysis: `.artifacts/fiber_v2_dynamic_step/sphere_f2_sqp_iteration_analysis_node10.json`
- Diagnostic chart: `.artifacts/fiber_v2_dynamic_step/sphere_f2_sqp_iteration_analysis_node10.png`
- Four-stage obstruction render: `.artifacts/fiber_v2_dynamic_step/sphere_f2_sqp_iteration_stages_node10.png`

The selected diagnostic fields follow the same practical categories used by mature
nonlinear optimizers: objective, primal feasibility, dual/stationarity residual,
step size, regularization/conditioning, acceptance fraction, and line-search decision.
See the official Ipopt iteration output and option references:

- https://coin-or.github.io/Ipopt/OUTPUT.html
- https://coin-or.github.io/Ipopt/OPTIONS.html

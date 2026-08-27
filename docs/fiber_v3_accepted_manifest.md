# Fiber V3 accepted-logic manifest

Date: 2026-08-27

## Purpose

`fiber-v3-production-1` is an internal opt-in production boundary for the exact
solver configuration visually accepted as `REG_ADAPTIVE_SPACING`. It filters the
accepted implementation out of the experimental V2 modules without changing its
finite-work objective or stopping behavior. V2 remains the default engine.

## Canonical policy

| Behavior | Production value | Experimental source |
|---|---:|---|
| Span solver | hard-midpoint span-SQP | `v3.spans` and `v3.solver` |
| Length | true polyline-length IRLS | `V2ContactPolicy.true_length_irls` |
| IRLS epsilon | `1e-4 × mean reference edge` | `true_length_epsilon_ratio` |
| Curvature | `0` | `REG_ADAPTIVE_SPACING` request ablation |
| Reference fidelity | `0.01 × captured weight` | true-length fidelity ablation |
| Spacing trigger | 4 accepts and segment CV above `0.75` | adaptive-quality experiment |
| Spacing ratio | `0.5 × length_weight / mean edge` | adaptive-quality experiment |
| Initial regularization | `1e-6 × median structural diagonal` | regularized-SQP experiment |
| Regularization | accepted adaptive controller | `REG_ADAPTIVE_SPACING` |
| Work budget | one global cap across spans | corrected span-SQP experiment |
| Reference cap | 180 accepted steps | accepted Blender comparison |

The output is the last independently validated working state when the solver
converges, genuinely stalls, or reaches the final accepted-step cap. V3 neither
continues beyond that cap nor substitutes an earlier state using visual metrics.

## Accepted foundation

- Pure-data numeric contracts and the V1/V2/V3 engine registry.
- Native ABI 3 banded solve, all-contact acquisition, CCD and static validation.
- P4.3 planner, P5.1 contact processing, P6.1 dispatch and V2.1–V2.4 reuse work.
- Local owner exemptions, containment handling and pin/surface recovery.
- Integrated unilateral contacts, infeasible-start filtering and limiting-pair injection.
- Cached native loader, reusable contact buffers and vectorized swept segments.
- Deterministic native parallelism for contacts, nearest-point queries and static validation.

Native workers write only independent indexed rows. Reductions and output aggregation retain
their original serial order, while CCD remains serial because changing its reduction can change
the nonlinear solver trajectory. The selected worker count is recorded in backend provenance,
diagnostics and cache identity.

The machine-readable authority is `core/vcp/v3/manifest.py`; the immutable
numeric authority is `core/vcp/v3/policy.py`.

## Rejected and unreachable

Production V3 does not import or activate Packages 7.x/8.x, V2.5, Anderson
acceleration, stable-limiter identity, contact-manifold reduction, composite/SOC
SQP, GCP, OGC, IMLS, Planar-DAT, high-order Fiber experiments, curvature
restoration, or the corridor/joint/covariant/transverse V3 experiments.

Rejected solver and acceleration modules were removed. Their names remain in the
machine-readable deny-list so import-graph tests prevent accidental restoration.

## Shortcut isolation

The additional continuous ROADMAP chord shortcut is seed-only and has three
internal modes: `OFF`, `SHADOW`, and `ON`. Production defaults to `OFF`.
`SHADOW` measures the shortcut but returns the unmodified planner seed. `ON`
requires collision validation for every replacement chord. Shortcut mode is part
of the request policy fingerprint and never changes the objective or validator.

Solver parity is measured with shortcut `ON`, matching the accepted experiment.
Shortcut impact is qualified separately before any future default change.

## Runtime contract

Set `AF_FIBER_ENGINE=V3` before a request to select V3. With no variable, V2
remains selected. Open Fibers run V3; cyclic/symmetric loops record a V1
compatibility fallback. A missing ABI 3 backend fails closed.

For live edits, `iterations_interactive` is a non-persistent validated preview
checkpoint. The same session continues to `iterations_bake`, then commits a safe
`CONVERGED`, `STALLED`, or `BUDGET_EXHAUSTED` result. Only a successful commit
sets `solver_version=3` and V3 provenance.

## Regression authority

- Unit parity checks deterministic V3 span-SQP output at an identical fixed cap.
- Import isolation verifies rejected modules are absent after importing V3.
- Blender workflow tests verify V3 selection, final-budget capture, migration and provenance.
- Real-file parity authority remains sphere `FIBER_2` and skeleton `FIBER_1` at cap 180.

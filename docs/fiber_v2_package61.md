# Fiber V2 Package 6.1 — Dynamic Trust/Certificate Activation

## Status

Package 6.1 is an isolated V2 experiment. It does not replace V1, alter saved
Fibers, publish runtime output, or enable V2 by default.

Package 6 reduced collision-pair work on the dense Skeleton/FIBER_1 fixture,
but its trust-bound and distance-certificate setup was overhead on smaller
collision workloads. Package 6.1 adds a deterministic dispatcher that selects
the exact Package 5.1 or Package 6 algorithm before the first accepted step.

The experiment passed its dispatch, overhead, output-parity, and targeted
performance hypotheses. It does not fix the remaining convergence failures and
is therefore not a rollout candidate by itself.

## Decision rules

The dispatcher builds the Package 4.3 planner reference and the first Package
5.1 candidate exactly once. It then applies the following ordered rules:

1. Count broad-phase pairs for the unbounded Package 5.1 candidate.
2. Select Package 5.1 immediately when there are fewer than 256 pairs or fewer
   than 4 pairs per Fiber edge.
3. For a dense workload, construct the exact Package 6 trust-bounded pilot and
   count its broad-phase pairs.
4. Select Package 5.1 when that bound removes less than 50% of the pairs.
5. Select Package 5.1 when the bounded workload falls below the same 256-pair
   or 4-pairs-per-edge amortization thresholds.
6. Otherwise classify at most 128 bounded pairs with conservative distance
   certificates.
7. Select Package 6 only when at least 70% of the sample is certifiably
   excludable. Uncertain pairs count against activation.

The rules are fail-safe with respect to performance: they only choose between
two already qualified algorithms. They never exclude a collision pair from a
selected solver, weaken validation, or alter the planner reference.

## Why these signals

- **Pair count** estimates the absolute opportunity to amortize dispatch and
  certificate work.
- **Pairs per edge** separates a genuinely dense swept workload from a longer
  Fiber with little local collision work.
- **Bounded-pair compression** measures whether Package 6's trust proposal
  actually shrinks the swept broad phase on this exact state.
- **Certificate sample yield** measures whether the remaining pairs are far
  enough to avoid native narrow-phase CCD.

This follows the same general principle as adaptive CCD culling: a conservative
bound is useful when it rejects substantial work, but an overly restrictive
bound may add steps and reduce performance. The dispatcher measures both the
available work and the expected rejection before activation.

Primary references: the [IPC paper](https://ipc-sim.github.io/file/IPC-paper-350ppi.pdf)
and its [technical supplement](https://ipc-sim.github.io/file/IPC-supplement-A-technical.pdf)
describe conservative CCD culling and its iteration/runtime tradeoff; the
trust-bounded Package 6 proposal follows the standard model-quality rationale
described in [Trust Region Methods](https://epubs.siam.org/doi/10.1137/1.9780898719857).

## Implementation

Package 6.1 adds:

- `V2CollisionWorkload` and `probe_collision_workload` for bounded workload
  inspection;
- `V2Package61Trace`, which records every input and branch decision;
- `solve_package61`, which dispatches into the exact Package 5.1 or Package 6
  iteration path;
- bounded certificate sampling that stops after the requested sample instead of
  materializing every candidate row;
- stable pair/distance cache priming so the probe's exact work is reused by the
  selected solve.

Every new or modified function remains at most 15 lines.

## Real-Blender benchmark method

- Blender 5.0.1, Windows workstation.
- Seven warmed repetitions per algorithm and Fiber.
- Randomized algorithm order with seed `6106`.
- Identical immutable collider snapshot and Package 4.3 planner reference.
- V1, Package 5.1, Package 6, and Package 6.1 measured separately.
- All source `.blend` files opened read-only and verified byte-identical.
- Every Package 6.1 output independently validated and compared point-for-point
  with the solver selected by the dispatcher.

Source hashes:

| File | SHA-256 |
|---|---|
| `skull_muscles.blend` | `A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06` |
| `skull_muscles_skin.blend` | `2EE614CAC26E65580322013DD7A80D6AF6360D49F26CDB2CEB0D0E9A768BFA96` |
| `skeleton_comb_base.blend` | `419029BA2C345F07008F8EB43ABF1DB4599C393692E77FE684CB13CC7560BD42` |

## End-to-end results

Median wall time in milliseconds:

| Fixture | V1 | P5.1 | P6 | P6.1 | Selected |
|---|---:|---:|---:|---:|---|
| Skull/FIBER_4 | 41.79 | 161.70 | 315.40 | **153.30** | P5.1 |
| Skull/FIBER_9 | 42.78 | 150.50 | 236.35 | **147.43** | P5.1 |
| Skull/FIBER_13 | 124.31 | 24.85 | 24.94 | **25.41** | P5.1 |
| Skull/FIBER_14 | 117.11 | 93.87 | 133.38 | **95.34** | P5.1 |
| Skull/FIBER_22 | 123.72 | 32.77 | 59.88 | **32.59** | P5.1 |
| Skull-skin/FIBER_1 | 97.35 | 83.53 | 146.37 | **87.65** | P5.1 |
| Skeleton/FIBER_1 | 80.07 | 319.15 | 210.52 | **209.63** | P6 |

On the dense skeleton case, Package 6.1 is 34.3% faster than Package 5.1 and
within 0.4% of Package 6. On all other cases it avoids the Package 6 regression
and stays close to Package 5.1. The small positive and negative differences
around Package 5.1 are benchmark noise plus the measured dispatch cost.

## Rule cost and decisions

| Fixture | Mode | Rule median | Rule p95 | Share | Base pairs | Bounded | Compression | Sample yield |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Skull/FIBER_4 | P5.1 | 0.329 ms | 0.394 ms | 0.21% | 481 | 280 | 42% | not sampled |
| Skull/FIBER_9 | P5.1 | 0.256 ms | 0.314 ms | 0.17% | 279 | 130 | 53% | not sampled |
| Skull/FIBER_13 | P5.1 | 0.082 ms | 0.143 ms | 0.32% | 87 | 87 | 0% | not sampled |
| Skull/FIBER_14 | P5.1 | 0.175 ms | 0.299 ms | 0.18% | 257 | 138 | 46% | not sampled |
| Skull/FIBER_22 | P5.1 | 0.108 ms | 0.131 ms | 0.33% | 174 | 174 | 0% | not sampled |
| Skull-skin/FIBER_1 | P5.1 | 0.112 ms | 0.187 ms | 0.13% | 245 | 245 | 0% | not sampled |
| Skeleton/FIBER_1 | P6 trust | 3.272 ms | 3.731 ms | 1.56% | 2,169 | 368 | 83% | 128/128 |

The cheap exits cost 0.08–0.33 ms median. The only full decision costs 3.27 ms,
but it protects a 109.5 ms median saving versus Package 5.1. Decision mode was
stable across all seven repetitions.

## Correctness and visual result

- All seven Package 6.1 results passed independent node and edge validation.
- Maximum point delta from the selected reference solver was exactly `0.0` in
  every fixture.
- Package 6.1 is visually identical to Package 6 on Skeleton/FIBER_1.
- Package 6.1 is visually identical to Package 5.1 on all six nonactivated
  fixtures.
- Package 6.1 preserved the selected solver's termination state; it did not
  relabel blocked or budget-exhausted output as converged.

Rendered PNGs and directly inspectable comparison `.blend` files are in
`artifacts/fiber_v2_package61/`. Each comparison is left-to-right: V1,
Package 4.3 planner, Package 5.1, Package 6, Package 6.1.

## Conclusion

Dynamic activation is the correct direction for Package 6. The workload is not
well represented by Fiber count or collider count alone; the actual first
candidate's pair density, trust compression, and conservative exclusion yield
predict whether Package 6 will pay for itself.

Package 6.1 should remain the experimental collision-policy entry point while
V2 convergence is repaired. It is ready to replace unconditional Package 6 in
future experiments, but not to enable V2 in the product: six of seven fixtures
still terminate `BLOCKED`, and Skeleton/FIBER_1 remains
`BUDGET_EXHAUSTED` despite returning independently valid geometry.

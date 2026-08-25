# Fiber V2 production-3 collision-core report

Date: 2026-08-20

## Outcome

`fiber-v2-production-3` is implemented as the open-Fiber production facade.
It replaces the former proposal/project/reject sequence with one augmented-
Lagrangian structural/contact iteration. The planner is now only an optional
initial seed. Native ABI 3 supplies all-contact queries, block-pentadiagonal
contact assembly/solve, CCD, and independent static validation.

The implementation is correctness-useful but **not rollout-qualified**. All
five measured real Fibers produced independently validated, publishable
results. None satisfied the strict convergence tests within the stored
interactive accepted-step cap, and several latency/slice gates still fail.

The design follows the active-contact and multiplier strategy described in
[Penetration-Free Elastodynamics without Barriers](https://arxiv.org/abs/2512.12151),
infeasible-start filtered acceptance from
[filter-SQP](https://www.sciencedirect.com/science/article/abs/pii/S0096300311006746),
and conservative feasible-state acceptance from
[IPC](https://ipc-sim.github.io/). The block-banded contact assembly retains the
structural sparsity motivation of
[Efficient IPC with Projective Dynamics](https://cgl.ethz.ch/publications/papers/paperYan23b.php).

## Implemented production path

- Contract version 2 reads version 1 payloads and writes version 2 payloads.
- Engine version is `fiber-v2-production-3`; native ABI/capability version is
  `af_fiber_ccd-3.8191`.
- The fixed reference `q` is the exact-count piecewise-linear curve through
  authored pins. Planner and warm results are seeds only.
- Node and edge contacts are acquired natively and stored with feature identity,
  normal, gap, multiplier, age, and clear streak.
- Contiguous contacts are grouped per collider and given a deterministic
  coherent escape side.
- The native block-pentadiagonal solve assembles structural and unilateral
  contact terms together. It does not use Package 8's dense Schur response.
- Invalid seeds use the same contact iteration with lexicographic feasibility
  acceptance. A no-planner DIRECT-through-box regression reaches a valid path.
- Feasible motion uses resumable conservative CCD. A newly limiting pair is
  injected and the structural/contact system is re-solved.
- Final publication uses a separate native static validator; projection data is
  never accepted as proof of safety.
- `SOLVING_INFEASIBLE` is transient and stale. It cannot write point JSON,
  generations, exact caches, provenance, or downstream outputs.
- Safe `STALLED` and `BUDGET_EXHAUSTED` results commit truthfully. Unsafe and
  backend-unavailable results do not commit.
- V2 capture and numerical solving are separated. CONTACT and CCD work is
  resumable; CCD advances at most 128 candidate pairs per step.
- The packaged Windows binary is `native/fiber_ccd/af_fiber_ccd_v3.dll`. Users
  do not need a compiler or external executable.

## Solver-only benchmark

Blender 5.0.1, Windows, 64 nodes, stored interactive cap of 12 accepted steps,
three repeats. `Capture` is Blender collider extraction and is excluded from
both V2 solver columns. `Full warm` is Capture + V2 warm and is the fairer
first-request approximation. V1 uses its existing monolithic call, so the V1
column is not a phase-identical comparison.

| File / Fiber | Capture ms | V1 ms | V2 cold ms | V2 warm ms | Full warm ms | Result |
|---|---:|---:|---:|---:|---:|---|
| `fiber_sphere/FIBER_2` | 6.3 | 154.3 | 132.2 | 124.6 | 130.9 | Valid, `STALLED` |
| `skull/FIBER_14` | 130.9 | 188.7 | 125.0 | 65.6 | 196.5 | Valid, `BUDGET_EXHAUSTED` |
| `skull/FIBER_1` | 129.5 | 355.0 | 250.4 | 257.6 | 387.1 | Valid, `STALLED` |
| `skull-skin/FIBER_1` | 131.4 | 422.6 | 261.4 | 252.7 | 384.1 | Valid, `STALLED` |
| `skeleton/FIBER_1` | 164.2 | 965.0 | 738.8 | 726.0 | 890.1 | Valid, `BUDGET_EXHAUSTED` |

The V2 numerical solve alone beats V1 for all five measured Fibers. Adding the
currently atomic Blender capture makes skull `FIBER_14` and `FIBER_1` slightly
slower than V1. This distinction is essential; solver-only numbers must not be
reported as complete request latency.

## Full runtime cycle

These measurements include request creation, capture, migration/publication,
curve application, and coordinator overhead.

| File / Fiber | Cold migration ms | Warm repeats ms | Property full cycle ms |
|---|---:|---:|---:|
| `skull/FIBER_14` | 369.2 | 164.6 / 212.5 / 234.7 | 260.4 |
| `skull/FIBER_1` | 516.8 | 481.1 / 475.5 / 363.0 | 284.8 |
| `skeleton/FIBER_1` | 1334.1 | 1147.2 / 904.9 / 1036.7 | 708.9 |

All three ended with 64-point `CURRENT` outputs independently validated under
the per-request numerical slack. The skeleton result remains too slow for live
editing.

## Cost diagnosis

The native factorization is not the bottleneck. Warm-run diagnostics were:

| Fiber | Contact ms | Factor ms | CCD ms | Validation ms | CCD pairs |
|---|---:|---:|---:|---:|---:|
| sphere `FIBER_2` | 18.6 | 0.216 | 76.1 | 6.4 | 1,985 |
| skull `FIBER_14` | 7.6 | 0.116 | 25.7 | 4.2 | 935 |
| skull `FIBER_1` | 26.9 | 0.247 | 126.5 | 11.9 | 3,898 |
| skull-skin `FIBER_1` | 31.7 | 0.247 | 127.5 | 12.5 | 3,595 |
| skeleton `FIBER_1` | 21.0 | 0.366 | 638.5 | 11.7 | 22,425 |

CCD is the dominant numerical cost, especially for the skeleton. Blender mesh
capture is the dominant cold overhead in the skull files. Further optimizing
the banded factor will not materially change end-to-end performance.

## Progressive scheduling

| Fiber | Initialization ms | Slices | p50 ms | p95 ms | Maximum ms |
|---|---:|---:|---:|---:|---:|
| sphere `FIBER_2` | 2.93 | 22 | 6.24 | 8.61 | 26.89 |
| skull `FIBER_14` | 5.28 | 22 | 5.93 | 18.86 | 32.73 |
| skeleton `FIBER_1` | 5.84 | 202 | 1.78 | 16.84 | 50.60 |

Immediate initialization passes the one-frame gate. The p95 and maximum slice
gates do not. Remaining long slices are atomic evaluated-mesh capture/BVH work
and some seed-contact acquisition. CCD itself is now pair-batched.

## Visual qualification

The side-by-side images show DIRECT, planner, V1, and production-3 paths in one
read-only copy. Production-3 is collision-valid in all shown cases.

- sphere `FIBER_2`: `../.artifacts/fiber_v2_p3/sphere_fiber2_owner_edge.png`
- skull `FIBER_14`: `../.artifacts/fiber_v2_p3/skull_fiber14_trust.png`
- skull `FIBER_1`: `../.artifacts/fiber_v2_p3/skull_fiber1_trust.png`
- skull-skin `FIBER_1`: `../.artifacts/fiber_v2_p3/skull_skin_fiber1_trust.png`
- skeleton `FIBER_1`: `../.artifacts/fiber_v2_p3/skeleton_fiber1_trust.png`

The source `.blend` files were opened read-only and retained these SHA-256
hashes after qualification:

- sphere: `D454901E8CE3031FA9E4401EEEF593BDB3B00AA705FBD3FC69880F2E4D936EC9`
- skull: `A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06`
- skull-skin: `2EE614CAC26E65580322013DD7A80D6AF6360D49F26CDB2CEB0D0E9A768BFA96`
- skeleton: `419029BA2C345F07008F8EB43ABF1DB4599C393692E77FE684CB13CC7560BD42`

## Qualification status

Passed:

- native block solve versus independent dense references;
- all-contact acquisition and adjacent-feature retention;
- conservative CCD adversarial/reference regressions;
- planner-disabled intersecting DIRECT seed reaches valid output;
- synchronous/resumable core and CCD result equivalence;
- localized owner contact beside unrelated blockers;
- exact-count, finite, independently validated publication;
- Fiber-focused Blender regression suite;
- function-size ratchet: no new or enlarged function exceeds 15 lines.

Not passed or not yet demonstrated:

- strict convergence on the five real examples within 12 accepted steps;
- progressive p95 at most 12 ms and maximum below 20 ms;
- 64-node complete result within 250 ms for every qualification Fiber;
- two-Fiber skeleton SCP update below 200 ms;
- 24-Fiber first synchronization below one second;
- representative 512-node solve below 220 ms;
- 90% convergence across all production Fibers;
- cyclic/symmetric V2, which intentionally remains the recorded V1 fallback;
- one explicit shared immutable collider capture for an entire SCP batch.

Therefore production-3 should remain qualification-gated. The correct next
optimization targets are persistent evaluated-mesh/native BVH capture and CCD
candidate reuse/reduction. Collision thresholds or validation must not be
weakened to meet the timing gates.

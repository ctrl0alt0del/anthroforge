# Fiber V2.2 — Generation-Keyed Live Request Experiment

## Decision

V2.2 successfully fixes the geometry-signature amplification found in V2.1 and
formalizes preview-versus-final planner reuse. It remains an isolated solver
experiment rather than a product rollout.

- Full collider-rich request signing falls from an average `281.68 ms` to
  `0.202 ms`, a 99.93% reduction.
- Generating a collision-snapshot digest during Blender capture costs an average
  `1.57 ms`.
- The persistent native snapshot cache records one build and 28 hits in every
  five-repeat real-file scenario.
- Aggregate uncached property-edit request time is 77.92% lower than V2.1.
- Aggregate uncached handle-preview request time is 76.84% lower than V2.1.
- Every V2.2 baseline, property, preview, and fresh-final result passes the
  independent native node/edge validator.
- Baseline, property, and fresh-final points are exactly equal to P6.1 in all
  eight fixtures.

V2.2 does not repair V2 convergence. Only Skull/FIBER_13 is `CONVERGED`; six
fixtures remain `BLOCKED` and Skeleton/FIBER_1 remains `BUDGET_EXHAUSTED`.

## Implementation

### Compact, fail-safe request identity

V2.1 used `V2Request.signature()`, which serialized every collider vertex and
triangle into JSON. Each new property or handle request therefore repeated a
237–334 ms Python traversal even when the same immutable collider snapshot was
already available.

V2.2 signs only:

- contract and engine versions;
- stable scene/root/source identities;
- settings, tolerances, collision policy, anchors, and symmetry;
- collider ID, owner, explicit generation token, and topology counts.

The capture benchmark computes a BLAKE2 digest while collider arrays are already
contiguous. The digest becomes part of each collider generation token. Missing
generation tokens fail back to the complete legacy geometry signature; V2.2
never assumes that an unversioned collider is unchanged.

The compact signature is also written directly into `V2Result`. This closes a
second hidden full serialization that initially remained at final-result
construction.

### Persistent shared snapshot

V2.2 addresses the existing bounded native triangle-snapshot cache by:

`scene ID + root ID + ordered collider generation records`.

Two different Fiber requests with the same collision generation receive the
same immutable triangle/native-BVH snapshot. A changed collider generation
creates a new cache record and invalidates route reuse. The cache remains
bounded by the existing eight-entry policy and is cleared by the existing
load/history lifecycle hooks.

This is compatible with Blender's official dependency-graph model: update rows
distinguish geometry and transform changes, and evaluated IDs expose the latest
evaluated geometry ([DepsgraphUpdate API](https://docs.blender.org/api/5.0/bpy.types.DepsgraphUpdate.html),
[ID evaluated access](https://docs.blender.org/api/5.0/bpy.types.ID.html)). The
runtime adapter still needs to supply these generation tokens when V2 is wired
into production.

### Preview and final route policy

- Exact requests may reuse a fresh validated route.
- Non-surface property changes may reuse a fresh route because anchors,
  colliders, and collision policy are unchanged.
- Surface property changes always run fresh planning. This removes the V2.1
  `0.01205` world-unit surface-output discrepancy.
- Small open-Fiber handle edits may warp and independently validate the stored
  corridor only for an `INTERACTIVE` preview.
- A warped route is stored as non-fresh. A later final solve with the same
  request must execute full P4.3 planning before it can publish.
- Surface handle edits never warp the route; their preview already performs
  fresh planning, so the final solve can reuse that fresh result.
- Collider-generation changes prohibit route and snapshot reuse.

The policy follows the lazy validated-edge principle used by
[LazySP](https://arxiv.org/abs/1603.03490): cached topology is a proposal, while
native validation remains the collision authority.

### Collision acceptance

V2.2 retains V2.1's conditional collision policy unchanged:

- P6.1 trust/certificates for dense workloads;
- P5.1 curved feasible steps for surface routes or more than four active nodes;
- one native linear CCD probe for sparse contacts;
- fail-closed curved recovery whenever the linear probe clips or is uncertain;
- independent native static validation at final output.

## Qualification protocol

- Blender 5.0.1, Windows workstation.
- Fresh Blender background process per file/Fiber.
- Five repetitions per algorithm and edit scenario.
- V1, P6.1, V2.1, and V2.2 receive equivalent captured geometry.
- V2.2 uses its generation-keyed persistent snapshot path rather than a supplied
  one-off snapshot.
- Five sequential curvature-property changes.
- Five sequential handle movements of 0.1–0.5 collision radius.
- A V2.2 preview is followed by a separately timed fresh-final request.
- All supplied files remain read-only.

Source hashes:

| File | SHA-256 |
|---|---|
| `skull_muscles.blend` | `A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06` |
| `skull_muscles_skin.blend` | `2EE614CAC26E65580322013DD7A80D6AF6360D49F26CDB2CEB0D0E9A768BFA96` |
| `skeleton_comb_base.blend` | `419029BA2C345F07008F8EB43ABF1DB4599C393692E77FE684CB13CC7560BD42` |

## Warm numeric baseline

Complete solve and strict validation, median milliseconds. V2.1/V2.2 warm
columns do not include V2.1's first geometry-signature construction.

| Fixture | V1 | P6.1 | V2.1 | V2.2 |
|---|---:|---:|---:|---:|
| Skeleton/FIBER_1 | 74.42 | 206.90 | 170.13 | 173.25 |
| Skull/FIBER_1 | 38.68 | 67.07 | 22.92 | 23.81 |
| Skull/FIBER_13 | 115.61 | 26.61 | 7.92 | 9.07 |
| Skull/FIBER_14 | 95.60 | 88.08 | 37.72 | 39.79 |
| Skull/FIBER_22 | 122.47 | 29.89 | 21.76 | 22.55 |
| Skull/FIBER_4 | 37.87 | 146.62 | 90.72 | 89.05 |
| Skull/FIBER_9 | 46.37 | 151.66 | 114.93 | 115.90 |
| Skull-skin/FIBER_1 | 79.09 | 76.50 | 24.04 | 26.19 |
| **Aggregate** | **610.11** | **793.34** | **490.13** | **499.61** |

V2.2 is 1.93% slower than V2.1 in this deliberately warm numeric comparison,
mainly because compact identity is recomputed on every call while V2.1's giant
signature was precomputed and cached outside the timed solver. V2.2 remains
37.02% faster than P6.1 and 18.11% faster than V1 in aggregate.

## Actual new-request editing cost

V2.1 live cost is its warm numeric time plus the measured first full request
signature. V2.2 time already includes compact signing and persistent snapshot
lookup.

| Fixture | V2.1 property request | V2.2 property | V2.1 handle request | V2.2 preview | V2.2 fresh final |
|---|---:|---:|---:|---:|---:|
| Skeleton/FIBER_1 | 517.75 | 175.20 | 524.91 | 178.89 | 210.10 |
| Skull/FIBER_1 | 302.29 | 82.29 | 353.97 | 82.15 | 29.31 |
| Skull/FIBER_13 | 291.75 | 8.52 | 284.31 | 10.99 | 12.67 |
| Skull/FIBER_14 | 304.84 | 38.76 | 315.24 | 38.78 | 61.27 |
| Skull/FIBER_22 | 298.65 | 31.53 | 305.42 | 36.51 | 16.48 |
| Skull/FIBER_4 | 369.68 | 86.65 | 380.25 | 110.87 | 169.36 |
| Skull/FIBER_9 | 388.68 | 113.75 | 390.28 | 136.21 | 152.32 |
| Skull-skin/FIBER_1 | 304.19 | 76.66 | 362.80 | 81.28 | 24.72 |
| **Aggregate** | **2777.82** | **613.36** | **2917.19** | **675.68** | **676.22** |
| **V2.2 reduction** |  | **77.92%** |  | **76.84%** |  |

Surface property edits are intentionally slower than V2.1's isolated numeric
path because they now plan fresh. They are still far faster as actual new
requests because compact identity eliminates the repeated geometry traversal.

Every fresh-final handle result is below 211 ms after its preview on this
fixture set. Immediate numeric previews range from 10.99 to 178.89 ms; only the
small direct FIBER_13 case fits one 16.7 ms frame. The existing immediate
anchor-following provisional display remains necessary for true one-frame UI
response.

## Capture and identity costs

| Fixture | Blender capture | Digest | V2.2 cold solve | V2.1 full signature | V2.2 compact signature |
|---|---:|---:|---:|---:|---:|
| Skeleton/FIBER_1 | 327.55 | 2.00 | 451.61 | 329.06 | 0.220 |
| Skull/FIBER_1 | 210.08 | 1.76 | 294.09 | 269.96 | 0.180 |
| Skull/FIBER_13 | 223.46 | 1.43 | 181.85 | 280.38 | 0.160 |
| Skull/FIBER_14 | 242.30 | 1.65 | 245.44 | 263.64 | 0.150 |
| Skull/FIBER_22 | 188.81 | 1.40 | 238.70 | 279.19 | 0.270 |
| Skull/FIBER_4 | 215.14 | 1.36 | 353.40 | 280.48 | 0.220 |
| Skull/FIBER_9 | 181.45 | 1.36 | 334.03 | 277.49 | 0.180 |
| Skull-skin/FIBER_1 | 203.75 | 1.58 | 307.80 | 273.23 | 0.230 |

Capture remains expensive when an SCP geometry generation truly changes. The
gain is that it can now happen once per runtime request and the resulting
snapshot can be shared across all affected Fibers. Production integration must
not recapture the same generation per Fiber.

## Correctness and visual review

- Baseline P6.1/V2.2 point delta is exactly `0.0` in all eight fixtures.
- Property P6.1/V2.2 point delta is exactly `0.0` in all eight fixtures,
  including the two surface FIBER_1 cases that differed in V2.1.
- Fresh-final P6.1/V2.2 point delta is exactly `0.0` in all eight fixtures.
- Every preview and final result passes independent static node/edge validation.
- Seven previews differ from fresh P6.1 by at most `0.00220` world units.
- Skull/FIBER_14 preview differs by `0.04020` world units, but the fresh final
  returns exactly to P6.1. The render shows the preview on the same anatomical
  side of the obstacle without intersection.
- Termination remains unchanged: one converged, six blocked, one budget
  exhausted.

## Remaining work

1. Wire collider generation tokens and the shared snapshot into the actual
   runtime capture adapter.
2. Ensure one SCP request captures once and distributes the same snapshot ID to
   every affected Fiber.
3. Keep warped routes transient and stale; only fresh-final results may commit.
4. Retain the generation-missing full-signature fallback.
5. Continue fixed-point/contact convergence work separately. V2.2 improves live
   request cost but does not make blocked output converged.
6. Preserve the immediate provisional display because the numeric preview does
   not consistently fit one frame.

## Artifacts

`artifacts/fiber_v22/` contains:

- `timing.png` — warm numeric and true uncached-request comparisons;
- eight JSON benchmark records with exact routes, phase traces, cache statistics,
  source hashes, validation, and signature measurements;
- eight four-column baseline Blender renders and review `.blend` files;
- eight four-column handle preview/final renders and review `.blend` files.

Baseline order: V1, P6.1, V2.1, V2.2. Handle order: P6.1, V2.1,
V2.2 preview, V2.2 fresh final.

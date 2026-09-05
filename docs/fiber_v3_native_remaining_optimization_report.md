# Fiber V3 remaining native optimization report

Date: 2026-08-30

## Outcome

Four exact-parity native optimizations were isolated and measured. Only dense-work CCD broad-phase
reuse is retained. Precomputed triangle records, SIMD packets, LTO, PGO, their experiment switches,
and their variant DLLs were removed. The unrelated pre-existing coordinator regression fixture
remains isolated from production.

The retained implementation caches a conservative fat swept bound and its triangle superset per
Fiber edge. A later exact swept bound may reuse that superset only while it remains contained by the
fat bound; every cached face is rechecked against the exact bound. Canonical face ordering and the
existing serial safe-fraction reduction are unchanged. Reuse activates only after a previous sweep
contains at least 512 candidate pairs, so sparse Fibers continue to query the BVH directly.

## Protocol

- Blender 5.0.1, Windows x64.
- Precompute and SIMD used one-process screening because they already failed performance or parity.
- LTO, PGO, and CCD reuse used `--background --factory-startup`.
- Final CCD comparisons alternated baseline and candidate in fresh processes.
- Read-only source files; SHA-256 checked before and after every run.
- Exact point hash, termination, accepted/rejected counts, and validation compared.
- Full solve, native contact, and native CCD time recorded separately.

The production qualification uses `skull_muscles.blend/FIBER_1`,
`skull_muscles.blend/FIBER_14`, and `skeleton_comb_base.blend/FIBER_1`.

## 4. Precomputed triangle data — partial implementation rejected

The variant stored contiguous triangle vertices, normals, bounds, and identity-transform shortcuts.
It preserved exact output. Its native collision-world records persisted across warm solves, but the
flattened CCD `TriangleSnapshot` was recreated by every new V3 session. The timings therefore reject
this partial representation, not a future generation-keyed precompute shared across recomputes.

Even in the persistent world, the representation increased data movement and cache footprint while
leaving the dominant closest-feature and CCD interval work unchanged.

Screening results:

| Fixture | Baseline | Precomputed | Change |
|---|---:|---:|---:|
| skull/FIBER_1 | 897.80 ms | 1005.09 ms | +11.9% |
| skull/FIBER_14 | 255.22 ms | 261.97 ms | +2.6% |
| skeleton/FIBER_1 | 2223.47 ms | 2238.20 ms | +0.7% |

## 5. AVX2/SIMD packets — rejected

Global `/arch:AVX2` changed accepted trajectories even with contraction disabled and therefore
failed correctness. A function-local `avx2,no-fma` four-AABB packet restored exact parity, but the
BVH leaves were too small and incoherent to amortize packing and mask extraction.

Screening results:

| Fixture | Scalar | Exact local AVX2 | Change |
|---|---:|---:|---:|
| skull/FIBER_1 | 897.80 ms | 908.38 ms | +1.2% |
| skull/FIBER_14 | 255.22 ms | 248.51 ms | -2.6% |
| skeleton/FIBER_1 | 2223.47 ms | 2347.95 ms | +5.6% |

## 6. LTO and PGO — rejected

PGO training covered sphere, skull, skull-skin, and skeleton fixtures. Both PGO and LTO preserved
exact results. LTO improved the skull screening run but regressed skeleton. PGO's clean two-repeat
screen looked promising, but independent fresh-process means reduced that to noise: skull/FIBER_1
improved 0.8%, skeleton was unchanged, and skull/FIBER_14 regressed 3.2%. No profile artifact or
special compiler path is retained.

## 7. CCD broad-phase reuse — accepted with dynamic activation

The dense skeleton solve performs about 487k CCD candidate tests, versus 18.5k and 8.3k for the two
skull Fibers. That separation supports a deterministic previous-sweep threshold rather than paying
cache maintenance on every solve.

Final paired fresh-process results:

| Fixture | Baseline full | Reuse full | Baseline CCD | Reuse CCD | Verdict |
|---|---:|---:|---:|---:|---|
| skeleton/FIBER_1 | 1973.74 ms | 1964.19 ms | 243.84 ms | 222.28 ms | retain; CCD -8.8%, full -0.5% |
| skull/FIBER_1 | 567.98 ms | 571.41 ms | 20.80 ms | 20.89 ms | gate inactive; run noise |
| skull/FIBER_14 | 227.45 ms | 237.59 ms | 9.60 ms | 9.73 ms | gate inactive; run noise |

Means on skeleton were 1975.80 ms baseline and 1953.21 ms with reuse, a 1.1% full-cycle gain. The
honest claim is therefore an 8.8% improvement to dense CCD broad phase and approximately 1% to the
whole heavy solve—not a multi-fold solver acceleration.

## Correctness

Production rebuild hashes matched the baseline variants exactly:

| Fixture | Point SHA-256 | Termination | Accepted/rejected |
|---|---|---|---:|
| skull/FIBER_1 | `035251448bc8fe4e` | STALLED | 180 / 100 |
| skull/FIBER_14 | `993822206d21e40f` | STALLED | 76 / 30 |
| skeleton/FIBER_1 | `5d66ad8823629e4b` | CONVERGED | 640 / 49 |

All results were independently validated and every source `.blend` hash remained unchanged.

## References

- Clang's official PGO/LTO guidance: <https://clang.llvm.org/docs/UsersManual.html>
- Intel's official AVX/AVX2 intrinsic reference: <https://www.intel.com/content/www/us/en/docs/intrinsics-guide/index.html>
- Box2D's official dynamic AABB-tree documentation and fat-AABB API:
  <https://box2d.org/documentation/group__tree.html>

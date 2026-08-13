# Fiber CCD development pilot

Status: development reference only, disabled by default, not a V2 rollout gate.

## Decision

The pilot does not bundle or activate IPC Toolkit. `ANTHROFORGE_FIBER_CCD_PILOT=reference`
enables an isolated pure-data reference call for development; no environment value changes the
Fiber solver or runtime path. Requesting `ipctk` fails closed with an explicit packaging-approval
error.

The reference performs swept moving-segment/static-triangle checks in world space. It first rejects
invalid starts, applies an inflated swept-AABB filter, and then subdivides time. Segment/triangle
distance is Lipschitz-continuous under linear endpoint motion: a midpoint distance minus maximum
endpoint speed times the interval half-width is a lower bound. Intervals whose lower bound exceeds
the requested clearance are certified clear; unresolved leaf intervals and exhausted budgets report
possible collision. This is deliberately conservative and may stop early. Float64 guards and
fail-closed tests make it useful as a development oracle, but it is not a formally interval-certified
production backend.

For multiple candidate pairs, each primitive is evaluated on the current global safe prefix. If its
local safe fraction is `s` and the current global prefix is `T`, the new prefix is `T*s`. Earlier pairs
were already certified over at least `T`, so shrinking the prefix preserves them. The focused test
`test_pair_steps_compose_in_global_time` covers this mapping with two collision planes.

## IPC Toolkit 1.6 gate audit

Audit date: 2026-08-13.

- The official CCD API supports `compute_collision_free_stepsize`, `is_step_collision_free`, and a
  minimum distance, but requires the initial configuration to be intersection-free and assumes a
  linear trajectory ([IPC Toolkit CCD API](https://ipctk.xyz/python-api/ccd.html)).
- PyPI 1.6.0 has CPython 3.11 wheels for Windows x86-64, manylinux x86-64, and macOS arm64, but no
  macOS x86-64 CPython 3.11 wheel ([IPC Toolkit on PyPI](https://pypi.org/project/ipctk/)).
- The downloaded Windows CPython 3.11 wheel is 2,131,263 bytes and contains a native `.pyd`, an MSVC
  runtime DLL, the IPC MIT license, and full source. Its metadata requires both NumPy and SciPy.
- Clean Blender 5.0.1 on the benchmark machine uses Python 3.11.13 on Windows AMD64. NumPy is present;
  SciPy and `ipctk` are absent. Therefore the wheel is not a clean-install dependency by itself.
- IPC Toolkit is MIT licensed ([IPC Toolkit license](https://github.com/ipc-sim/ipc-toolkit/blob/main/LICENSE)),
  but its default CMake configuration enables and publicly links FILIB
  ([IPC Toolkit CMake](https://github.com/ipc-sim/ipc-toolkit/blob/main/CMakeLists.txt)). [IPC's own
  dependency guidance identifies FILIB as LGPL-2.1 and warns that default static linkage creates a
  licensing challenge](https://ipctk.xyz/about/dependencies.html). The audited wheel
  exposes only IPC's MIT license in `dist-info/licenses`. Legal and binary-composition review, or an
  approved FILIB-disabled build, is mandatory before distribution.
- Blender extensions must bundle declared wheels and their dependencies rather than assume packages
  from the host interpreter ([Blender wheel rules](https://docs.blender.org/manual/en/dev/advanced/extensions/python_wheels.html)).

IPC therefore fails current dependency, platform, and legal/build gates. It was not installed,
imported, integrated, or adopted.

## Correctness coverage

`tests/unit/test_fiber_ccd_reference.py` covers:

- a crossing whose start and end are both clear;
- face, coplanar, exact-clearance grazing, thin-triangle, and degenerate-triangle cases;
- initially invalid and static configurations;
- fail-closed interval-budget exhaustion and nonfinite rejection;
- a localized owner-contact pair filter;
- global safe-prefix composition across multiple triangles;
- deterministic randomized motions compared with 201 dense time samples, with no reference result
  labeled clear when a dense sample observes contact;
- explicit development-flag behavior and IPC's unapproved status.

This test set is an adversarial development comparison, not proof of zero misses. A production
backend still needs the full brute-force/adversarial sweep matrix, transformed fixtures, and exact
clearance validation from the release plan.

## Read-only production benchmark

Command:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.0\blender.exe' --background --factory-startup `
  --python tools\fiber_ccd_probe.py -- `
  --blend 'E:\development\WIP_models\skull_muscles.blend' `
  --fiber FIBER_14 --nodes 64,256,512 --clearance 0.002 --motion 0.002 --repeat 2
```

Fixture SHA-256 before and after:
`a7c4033ab2eb7479eaec4a069cb1d7ddf9fecc5d5c43037863b02a9f9bb7ef06`.
The evaluated collider snapshot contains 15,460 vertices and 30,544 triangles. The candidate moves
the persisted FIBER_14 centerline by a smooth 2 mm world-Z displacement, keeps endpoints fixed, and
uses the solver's local owner-contact zones.

| Nodes | Candidate pairs | Tested pairs | Intervals | Run 1 | Run 2 | Result |
|---:|---:|---:|---:|---:|---:|---|
| 64 | 74 | 46 | 46 | 72.77 ms | 78.51 ms | clear |
| 256 | 227 | 184 | 196 | 293.27 ms | 277.24 ms | clear |
| 512 | 435 | 353 | 389 | 545.89 ms | 540.33 ms | clear |

The reference scales close to tested-pair count, but a single 512-node validation already costs
about 543 ms. That exceeds the entire 220 ms representative-solve target before solver work, final
validation, or downstream publication. It is therefore impractically slow for production.

An intentionally narrower endpoint-only owner filter made persisted paths report `INVALID_START` at
64 and 256 nodes. This demonstrates why legal owner contact must use solver-derived local zones and
why existing stored paths cannot be labeled CCD-safe without explicit initial validation. The stricter
result is diagnostic, not a rollout gate.

## Exact production blocker

The reference's broad phase is vectorized and triangle bounds are precomputed, but every surviving
edge/triangle pair still executes Python/NumPy scalar geometry and interval subdivision. At 512 nodes,
353 pair tests and 389 intervals consume roughly 543 ms. Production needs a supported native
broad-phase plus conservative swept segment/triangle kernel, localized owner filtering that remains
below 20% overhead, and packaging/legal approval. Until one backend passes zero-miss and clearance
comparisons and is at least twice as fast (or demonstrably required for end-to-end targets), V2 remains
on its current conservative backend and this reference remains development-only.

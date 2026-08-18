# Fiber V2 production integration specification

Date: 2026-08-18

## Decision

AnthroForge will have one production Fiber engine selector:

- code default: `V2`;
- environment override: `AF_FIBER_ENGINE=V1` or `AF_FIBER_ENGINE=V2`;
- no solver selector in the UI;
- an absent environment variable selects the code default;
- an invalid value is a configuration error and never silently selects an engine;
- engine selection is captured once per request and cannot change inside a job.

V2 must never silently fall back to V1 after an open-Fiber V2 request starts.
Cyclic and symmetric-loop requests use the temporary, explicit
`V2_TOPOLOGY_COMPATIBILITY` V1 fallback selected before execution. Missing V2
backend, invalid configuration, attachments, or captured data never trigger V1;
the request terminates truthfully and retains the last-good output.

## Implementation and qualification status

The production boundary described here is implemented, but V2 is **not rollout
qualified**. The code default requests V2, the internal V1 override works, and
publication is fail-closed. Real-file qualification found correctness and
latency failures that must be fixed before this default is suitable for a
release build.

Implemented on 2026-08-18:

- strict request-local selection in `core/vcp/fiber_engine_selection.py`;
- stable registry and accepted-only `solve_v2` production facade;
- explicit V1 topology compatibility provenance for cyclic/symmetric loops;
- one selector for progressive, synchronous, Quick Fiber, Recompute, property,
  handle, SCP, and final-quality entry points;
- token-owned V1/V2 transition snapshots and atomic commit/rollback;
- committed engine/backend provenance and versioned cache identity;
- fail-closed missing backend and invalid-selector results;
- failed-preview retention without point JSON, generation, cache-publication, or
  downstream publication;
- round-robin enqueue/drain for affected-Fiber runtime work;
- focused selector, topology, migration, cancellation, supersession,
  publication, cache, and compatibility regressions.

Not yet complete:

- the accepted V2 solve is still atomic after collider capture; the PLAN,
  CONTACTS, GLOBAL, CCD, and VALIDATE internals are not independently resumable;
- SCP work shares generation-keyed caches but not one explicit immutable
  batch-capture object;
- live SCP draining still blocks the runtime pass until the batch finishes;
- cyclic/symmetric-loop V2 remains a recorded V1 compatibility fallback;
- production-file correctness and several latency gates fail as recorded below.

## Canonical production V2

Production code must call one stable facade, `solve_v2`, with one version string
and one immutable feature manifest. The facade contains the accepted chain:

| Layer | Accepted behavior |
|---|---|
| Contracts | Pure-data V2 request, result, diagnostics, and precise termination |
| Structure | O(N) banded open/cyclic structural solve with exact pins |
| Collision authority | Packaged native CCD plus independent static validation |
| Planner | Package 4.3 native planner and unified collider/owner policy |
| Contact/acceptance | Package 5.1 fused contacts, pair cache, and curved recovery |
| Workload policy | Package 6.1 dynamic light/dense dispatcher |
| Reuse | V2.1 validated route reuse and linear-first CCD |
| Identity | V2.2 compact generation-keyed request and collider identities |
| Shared world | V2.3 generation-aware shared collision world |
| Native batching | V2.4 batch collision-world construction |
| Shape recovery | Accepted collision-safe hard-pin and surface recovery |
| ROADMAP recovery | Guarded local corner recovery with full CCD and final validation |

The following experiments are explicitly excluded:

- `solver_v25_branch2` and the rejected V2.5 branch experiment;
- Packages 7.1 and 7.2;
- Packages 8, 8.1, and 8.2 as complete solvers;
- every reference or Python collision backend as a production fallback.

### Package lineage clarification

The package numbers describe cooperating V2 layers, not one cumulative planner
binary. Package 4.3 therefore does not contain all earlier packages internally:

- Package 1 defines the immutable request/result contracts consumed by every
  later layer, including Package 4.3;
- Package 2 provides the banded structural solve used by the Package 5.1 solver
  phase after planning;
- Package 3 provides the collision snapshot, distances, owner policy, CCD, and
  independent validation used by Package 4.3 and later solver phases;
- Package 4.3 supersedes the planner implementation while preserving the
  Package 4 route semantics and Package 4.1 cached-metric search behavior;
- Package 4.2's grouped-route planner is excluded, while its accepted persistent
  native BVH/collision acceleration survives in the shared Package 3 backend.

Consequently the production stack explicitly assembles Packages 1, 2, and 3
with the Package 4.3 planner. It does not assume that choosing Package 4.3 alone
implicitly supplies the structural solver or every Package 4.2 experiment.

The initial facade version is `fiber-v2-production-1`. Any change that can alter
points, route selection, collision truth, or termination increments this version
and invalidates exact-result caches.

## Engine-selection contract

Add `core/vcp/fiber_engine_selection.py` with these responsibilities only:

```text
FiberEngineKind = V1 | V2
DEFAULT_FIBER_ENGINE = V2
FIBER_ENGINE_ENV = AF_FIBER_ENGINE
resolve_fiber_engine(explicit=None, environ=None) -> FiberEngineSelection
```

Resolution precedence is:

1. explicit injected selection, used only by tests and internal probes;
2. exact environment value `V1` or `V2`;
3. `DEFAULT_FIBER_ENGINE`.

The resolver reads the environment when a request is created. Changing
`os.environ` inside Blender affects later requests; changing the parent process
environment requires restarting Blender. Tests inject a mapping and do not
mutate global environment state.

Remove production reads of `AF_FIBER_V2_ROLLOUT` and
`AF_FIBER_V2_RUNTIME`. Tests and benchmark tools migrate to
`AF_FIBER_ENGINE`. Keeping two authorities would make creation, migration, and
runtime dispatch disagree.

## Architecture

### 1. Stable engine registry

Add `core/vcp/fiber_engine_registry.py` containing a small registry from
`FiberEngineKind` to an adapter factory. The registry exposes one operation:

```text
begin_selected_fiber_solve(capture_context, selection) -> FiberSolveSession
```

The V1 adapter wraps the corrected legacy session. The V2 adapter wraps the
pure-data V2 capture and `solve_v2`. `fiber_progressive.begin_fiber_solve` asks
the selector and registry; it contains no version-specific branching.

### 2. One V2 production facade

Add `core/vcp/v2/production.py`:

- exports `V2_PRODUCTION_VERSION`, `V2_PRODUCTION_FEATURES`, and `solve_v2`;
- delegates to the accepted implementation without importing rejected solvers;
- rewrites the public result engine version to the production version;
- owns production cache clearing and cache statistics;
- rejects an unavailable or incompatible native backend with
  `BACKEND_UNAVAILABLE`.

Runtime modules import `solve_v2`, never experimental solver names. Experimental
entry points remain available only to tests and benchmark tools until removed.

### 3. Engine-agnostic scheduling and publication

`fiber_refinement` remains the only scheduler and commit coordinator. Both
engines return the same `FiberSolveResult` contract. The coordinator owns:

- request tokens and supersession;
- provisional and failed-preview display;
- exact-count and finite checks;
- final publication and `FIBER_SOLVE_READY`;
- rollback to the last-good persisted output;
- downstream isolation for stale output.

No engine writes point JSON, output generations, downstream events, or RNA
properties directly.

### 4. Every solve entry uses the registry

The following paths must use the same selector and registry:

- handle edits;
- property edits;
- Quick Fiber creation;
- explicit Recompute;
- SCP transform/deformation updates;
- synchronous compatibility calls to `FiberSolver.solve_points`;
- final/bake requests.

The current direct synchronous Fiber driver must not bypass the accepted V2
engine. For V2, SCP changes enqueue one shared-collider refinement batch rather
than solving each Fiber synchronously inside the dependency driver. The
synchronous public facade may explicitly drain a selected session, but live
runtime callers use progressive scheduling.

## Persisted compatibility and migration

`solver_version` becomes provenance for the last committed primary output. It
does not select the next engine. The global engine policy selects new work.

Rules:

1. Loading a file never launches a solve.
2. Persisted points are hydrated exactly as saved.
3. New Fibers use the selected engine; with no environment override this is V2.
4. The first edit or Recompute of a V1 Fiber under V2 starts an automatic,
   token-owned migration.
5. The original V1 points and diagnostics are snapshotted once.
6. Only a validated V2 commit sets `solver_version=2`.
7. Failure, cancellation, supersession, or missing backend retains the V1
   output and version.
8. `Restore Legacy Shape` remains available and restores the saved V1 snapshot.
9. Forcing V1 through the environment runs V1 for new requests. A successful
   V1 commit records V1 provenance but does not overwrite the retained legacy
   snapshot.

Add these internal output properties:

- `af_fiber_output_engine`: `V1` or `V2`;
- `af_fiber_output_engine_version`: exact engine build string;
- `af_fiber_output_backend_version`: native backend build string.

They are written atomically with committed points and generation. They are
diagnostic/provenance fields, not user controls.

## Result and preview policy

The engine-independent commit matrix is:

| Termination | Independently validated | Publication |
|---|---:|---|
| `CONVERGED` | yes | `CURRENT` and downstream event |
| `STALLED` | yes | `CURRENT`, truthful status, downstream event |
| `BUDGET_EXHAUSTED` | yes | `CURRENT`, truthful status, downstream event |
| `BLOCKED` | any | failed preview only; retain last-good primary |
| `NO_FEASIBLE_PATH` | any | failed preview only; retain last-good primary |
| `UNSAFE_OUTPUT` | no | retain last-good primary |
| `BACKEND_UNAVAILABLE` | no | retain last-good primary |
| cancelled/superseded | any | never commit or emit solve-ready |

A safe non-converged curve is therefore not rolled back merely because it
exhausted its accepted-step cap. It commits with an honest status. Rejected
internal iterates never become visible.

Display states remain separate from primary output state:

- `PROVISIONAL`: immediate anchor-following geometry;
- `VALIDATED_PREVIEW`: improved collision-safe preview;
- `FAILED_PREVIEW`: best visible unsuccessful attempt;
- `CURRENT`: committed independently validated output;
- `STALE`: last-good or provisional geometry that downstream consumers reject.

## Topology and backend requirements

The temporary topology policy is explicit and request-local:

- requested V1 uses actual V1 for all topologies;
- requested V2 uses actual V2 for open Fibers;
- requested V2 uses actual V1 for cyclic and symmetric-loop Fibers, recording
  `V2_TOPOLOGY_COMPATIBILITY` in selection, diagnostics, and provenance.

No runtime failure after open-Fiber V2 selection may invoke V1. Native support
for cyclic and symmetric-loop V2 is tracked as the next integration rather than
being hidden behind an implicit adapter return.

The packaged native DLL is mandatory for V2 collision movement and final static
validation. Users install no compiler or service. Missing ABI, DLL, export, or
backend version produces `BACKEND_UNAVAILABLE`; it never invokes V1 or a Python
reference backend automatically.

## Request, cache, and lifecycle identity

Every V2 request freezes:

- selected engine family and production version;
- native backend version;
- scene/root runtime identity;
- Fiber source revision and request token;
- quality, topology, node count, weights, and resolved tolerances;
- ordered authored anchors, owners, and roles;
- symmetry policy;
- collider topology, geometry generations, and transform generations;
- planner branch and exact-count handoff identity.

Exact, route, factor, collider-world, and capture caches include the production
engine version. V1 and V2 caches never share entries. Cache clearing covers
load, undo/redo, unregister, deletion/recreation, backend change, and production
engine-version change.

The capture cache must be bounded by entries and estimated bytes. One runtime
request shares one immutable collider snapshot across all affected Fibers.

## Scheduling

V2 numeric execution must not occur as one indivisible call inside
`V2RuntimeSession.step`. The accepted engine is wrapped as resumable phases:

```text
CAPTURE -> PLAN -> CONTACTS -> GLOBAL -> CCD -> ACCEPT -> VALIDATE -> DONE
```

Until every native phase has a resumable API, one native call may remain atomic,
but its measured maximum must stay below the slice gate. Scheduling priority is:

1. selected Fiber provisional preview;
2. other visible affected provisional previews;
3. selected Fiber validated refinement;
4. remaining affected Fibers round-robin;
5. downstream work after commits.

An SCP edit captures collider geometry once, then schedules affected Fibers.
Cancelled and superseded sessions release references immediately and cannot
publish.

## Telemetry

Every request records:

- `engine_family`, `engine_version`, and `backend_version`;
- selection source: explicit, environment, or code default;
- stored provenance before and after the request;
- migration started/committed/rolled back;
- planner branch and cache/reuse mode;
- light/dense dispatch decision;
- accepted, rejected, CCD-limited, and recovery trials;
- pin/ROADMAP recovery attempts and acceptance;
- node/edge residuals and final validation;
- capture, planner, contact, structural, CCD, validation, commit, and total time;
- progressive slice distribution and cache sizes.

This makes V1/V2 comparisons use identical full-cycle boundaries.

## Ordered implementation

### Integration 1: selection and facade

- Add the selector, registry, and canonical `solve_v2` facade.
- Replace both old flags with `AF_FIBER_ENGINE`.
- Version all V2 caches from the production facade.
- Add selector, invalid-value, missing-backend, and excluded-solver tests.
- Keep the code default V1 only on the integration branch until later gates pass.

### Integration 2: unify runtime entry points

- Route progressive, direct, Quick Fiber, Recompute, property, handle, and SCP
  paths through the registry.
- Remove property-based solver dispatch from `FiberSolver` internals.
- Make the V2 session fail closed rather than return `None`.
- Preserve public interfaces and result fields.

### Integration 3: topology and transitions

- Add explicit cyclic and symmetric-loop V1 compatibility selection.
- Make migration automatic on first requested solve, never on load.
- Make engine transitions token-owned and atomic.
- Persist output engine/backend provenance.

### Integration 4: scheduling and shared capture

- Replace synchronous V2 SCP solves with one progressive batch.
- Share one captured native world among affected Fibers.
- Split or bound the current monolithic numeric step.
- Enforce cancellation and round-robin fairness.

### Integration 5: qualification and default flip

- Run full clean unit and Blender suites.
- Qualify every authored Fiber in all supplied production files.
- Verify source files remain byte-identical.
- Package-test the DLL in a clean Blender installation.
- Set `DEFAULT_FIBER_ENGINE = V2`.
- Verify `AF_FIBER_ENGINE=V1` restores the complete V1 path and
  `AF_FIBER_ENGINE=V2` restores the complete V2 path.

Each integration is independently revertible. The default flips only after
Integrations 1-4 pass; the completed product nevertheless ships with V2 as the
code default.

## Release gates

Correctness:

- no silent cross-engine or topology fallback;
- planner, contacts, CCD, and final validator use one collider/owner snapshot;
- exact pins and requested node count;
- all committed V2 outputs independently validate;
- safe `STALLED` and `BUDGET_EXHAUSTED` results commit truthfully;
- unsafe and backend-unavailable results retain last-good output;
- V1/V2 switches cannot share exact or warm caches;
- load, undo/redo, cancellation, and deletion/recreation match clean state.

Compatibility:

- old files do not solve on load;
- existing V1 shapes remain until their first requested solve;
- automatic migration succeeds or rolls back atomically;
- Restore Legacy Shape works after successful V2 migration;
- public `FiberSolver`, `solve_points`, progressive entry points, route strings,
  result fields, and `FIBER_SOLVE_READY` remain available.

Performance on the current Windows workstation:

- input event p95 below 5 ms;
- provisional preview below 16.7 ms;
- progressive slice p95 at most 12 ms and maximum below 20 ms;
- representative 64-node validated interactive result within 250 ms after quiet;
- two-Fiber skeleton SCP update below 200 ms after quiet;
- 24-Fiber first synchronized result below 1 second, stretch target below 500 ms;
- representative 512-node solve below 220 ms;
- no cold capture per Fiber when one request affects multiple Fibers.

Rollout authority:

- real unmocked V1-to-V2 migration, failure, cancellation, and restore tests;
- open V2 plus cyclic and symmetric-loop compatibility-selection fixtures;
- all supplied production files and their benchmark hashes;
- V1 and V2 full-cycle A/B runs under the same event and timing boundaries;
- clean Blender install with and without the native DLL;
- no rejected experiment reachable from the production facade.

## 2026-08-18 real-file qualification

All timings below are full request-to-terminal measurements in Blender 5.0.1
on the current Windows workstation. A fast terminal failure is not counted as a
successful optimization. Source `.blend` files were opened read-only and their
SHA-256 hashes remained unchanged.

| Fixture | Engine | Cold ms | Warm ms | Property ms | Result |
|---|---:|---:|---:|---:|---|
| `skull_muscles/FIBER_14` | V1 | 1657.83 | 246.77-251.54 | 257.22 | safe `BUDGET_EXHAUSTED`, committed |
| `skull_muscles/FIBER_14` | V2 | 172.63 | 54.07-65.65 | 74.56 | `BLOCKED`, no V2 commit; the apparent speedup is early failure |
| `skull_muscles_skin/FIBER_1` | V1 | 441.26 | 86.81-89.27 | 91.30 | unsafe residual, stale |
| `skull_muscles_skin/FIBER_1` | V2 | 241.71 | 89.86-120.41 | 123.79 | safe `STALLED`, committed V2 |
| `skeleton_comb_base/FIBER_1` | V1 | 1302.74 | 378.58-391.96 | 363.67 | cold/interactive unsafe; later property solve committed |
| `skeleton_comb_base/FIBER_1` | V2 | 11025.56 | 183.88-197.48 | 245.91 | safe budget/stalled result, but unacceptable cold time |
| `skull_muscles/FIBER_13`, 512 nodes | V1 | 44.96 | 41.46 | 40.28 | `CONVERGED`, committed |
| `skull_muscles/FIBER_13`, 512 nodes | V2 | 182.56 | 78.07 | 83.69 | `CONVERGED`, committed |

Additional full-cycle measurements:

- 24-Fiber `skull_muscles` synchronization: V2 `1789.29 ms`, V1
  `4577.08 ms`. V2 is faster but fails the `<1 s` gate and includes seven
  blocked and six invalid-attachment outcomes, so it is not a successful
  correctness-qualified synchronization.
- feasible 512-node V2 `FIBER_13`: initialization `8.37 ms`, total
  `169.07 ms`, but slice p95/max `109.23 ms`; the solve is still effectively
  atomic and fails the `<=12/<20 ms` scheduling gate.
- a requested 512-node V2 `skull_muscles_skin/FIBER_1` blocked and retained its
  64-point primary output; it is not a valid 512-node throughput result.

| Gate | Status | Evidence |
|---|---|---|
| Selector/default/strict invalid value | PASS | focused unit and Blender tests |
| V1 topology compatibility provenance | PASS | focused topology tests |
| Missing V2 backend never invokes V1 | PASS | focused fail-closed tests |
| Atomic migration/publication | PASS | success, failure, cancellation, supersession tests |
| Representative 64-node result within 250 ms | MIXED | skin and warm skeleton pass; skull blocks |
| Representative 512-node solve below 220 ms | PASS on feasible direct fixture | V2 `182.56 ms` cold |
| Progressive p95 `<=12 ms`, max `<20 ms` | FAIL | p95/max `109.23 ms` |
| Two-Fiber skeleton SCP update below 200 ms | FAIL | warm single-Fiber work already reaches `183-246 ms` |
| 24-Fiber synchronization below 1 second | FAIL | `1789.29 ms` |
| Production correctness | FAIL | `skull_muscles/FIBER_14` blocks; several batch outcomes invalid |
| Cyclic/symmetric V2 | DEFERRED | explicit V1 compatibility fallback |

Qualification hashes:

- `skull_muscles.blend`: `A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06`
- `skull_muscles_skin.blend`: `2EE614CAC26E65580322013DD7A80D6AF6360D49F26CDB2CEB0D0E9A768BFA96`
- `skeleton_comb_base.blend`: `419029BA2C345F07008F8EB43ABF1DB4599C393692E77FE684CB13CC7560BD42`

Rollout verdict: **do not ship V2 as the user-facing production default yet**.
The selection code defaults to V2 as requested, but release packaging should
force `AF_FIBER_ENGINE=V1` until the blocked skull route, cold skeleton path,
bounded phase scheduling, and multi-Fiber batch gates are fixed.

Final verification:

- unit suite: `517/517` passed, with six native-binary skips in system Python
  and one pre-existing expected warm/cold-tolerance failure;
- Fiber-only Blender suite: `190/190` passed;
- complete Blender discovery: all Fiber tests passed; eight unrelated Draft
  Skin/topology tests could not initialize their existing SciPy vendor bundle
  because of `WinError 5` temporary-directory replacement failures and missing
  SciPy, so the complete repository suite is not clean in this environment;
- compilation, function-size ratchet, and `git diff --check` passed.

Environment behavior follows Python's [`os.environ` documentation](https://docs.python.org/3.11/library/os.html#os.environ).
The main-thread capture/commit design follows [Blender's threading restrictions](https://docs.blender.org/api/5.0/info_gotchas_threading.html).

## Expected code-level switch

Default behavior requires no environment variable:

```text
Blender -> V2
```

Developer fallback before starting Blender:

```powershell
$env:AF_FIBER_ENGINE = "V1"
```

Explicit V2 qualification:

```powershell
$env:AF_FIBER_ENGINE = "V2"
```

The value is intentionally strict. Truthy aliases, package numbers, and
per-feature environment switches are not accepted by the production selector.

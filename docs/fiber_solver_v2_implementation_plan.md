# Fiber Solver V2 — Complete Implementation Plan

Status: implementation roadmap from the current worktree to production rollout  
Last updated: 2026-08-14  
Primary product goal: deterministic, collision-safe static anatomical centerlines with excellent live-edit feedback  
Primary benchmark files: `skull_muscles.blend` and `skeleton_comb_base.blend` (always opened read-only)

## 1. Product decision

Fiber V2 is a static anatomical centerline optimizer. It is not a dynamic rod simulation and will not
model inertia, twist, self-collision, Fiber-to-Fiber collision, or physical animation.

The user experience has three layers:

1. Display a provisional, collision-validated planner route immediately.
2. Refine it progressively after input, publishing only safer or objectively better previews.
3. Commit a result only after exact pins, finite coordinates, exact node count, and collision safety
   have been independently validated.

Live handle dragging, property-slider editing, and synchronizing several Fibers after an SCP change
take priority over very high-node final-bake throughput. Final recompute remains available for
explicit high-quality work, but entering `1000` iterations must not be necessary to obtain a stable
answer.

## 2. Why V2 is needed

V1 is a useful compatibility solver but is not a well-defined length-and-curvature optimizer.
Its shortening and bending operations are algebraically the same Laplacian averaging update; bend
is merely applied as an additional pass on alternating iterations. Collision response locally pushes
nodes and segments away from obstacles, after which Laplacian smoothing can pull them back again.
There is no scalar objective or merit function that every accepted iteration must improve.

The screen recording `20260813-1958-23.4247266.mp4` demonstrates the consequence:

- one continuous refinement visually oscillates between different shapes, appearing to retry;
- the solve runs through multiple resolutions and displays raw intermediate iterates;
- with Segment Collisions disabled, a diagnostic reproduction remained nonconverged at 12, 30,
  120, and 1000 maximum iterations;
- the 1000-iteration diagnostic consumed about 7.4 seconds and ended with a worse displacement
  residual than several shorter runs;
- the current stall detector only recognizes almost bit-identical residuals, so a periodic
  oscillation is never classified as stalled.

More iterations are therefore not a reliable quality control. V2 must have a fixed mathematical
problem, monotone safeguarded acceptance, meaningful convergence residuals, and adaptive work
allocation.

## 3. Research basis

The numerical design follows the prefactorized local/global structure of
[Projective Dynamics](https://www.projectivedynamics.org/projectivedynamics.pdf). A correct
local/global solver alternates constraint projections with a global quadratic solve and decreases a
fixed target energy.

The first acceleration method will be safeguarded Anderson acceleration. Peng et al. treat a
local/global step as a fixed-point map, use a short history to predict a better iterate, and reject
the accelerated candidate when it does not decrease the target energy. This is directly aligned
with Fiber's small chain systems and interactive accuracy requirements:
[Anderson Acceleration for Geometry Optimization and Physics Simulation](https://archive.ymsc.tsinghua.edu.cn/pacm_download/523/11728-AALG.pdf).

Two alternatives remain comparison pilots, not initial production choices:

- [Chebyshev semi-iterative acceleration](https://wanghmin.github.io/publication/wang-2015-csi/Wang-2015-CSI.pdf)
  can reduce Projective Dynamics iteration counts substantially, but requires a useful spectral-radius
  estimate and becomes less robust when nonlinear contact projections change.
- [Quasi-Newton/L-BFGS acceleration](https://users.cs.utah.edu/~ladislav/liu17towards/liu17towards.pdf)
  is powerful but requires a safeguarded line search. Fiber collision evaluation currently makes
  extra line-search evaluations expensive, so this is a later comparison if Anderson is insufficient.

XPBD is intentionally excluded. Its principal advantage is time-step and iteration-independent
compliance for physical simulation; Fiber V2 has no physical time state.

## 4. Current implementation inventory

### 4.1 Implemented and retained

| Area | Current implementation | V2 use |
| --- | --- | --- |
| V2 quadratic core | Open pentadiagonal LDLT and cyclic low-rank Woodbury solve in `core/vcp/fiber_solver_v2.py` | Retain and extend |
| Complexity | O(N) factorization/solve, linear-memory factors | Retain |
| Hard pins | Pin degrees of freedom are eliminated exactly | Retain |
| Independent weights | Length and curvature terms are distinct and normalized by resolution | Retain |
| Core diagnostics | Energy components and stationarity residual exist | Promote into live convergence |
| Factor cache | Bounded cache keyed by topology/count/pins/weights | Extend with engine/contact policy |
| Runtime routing | Targeted dirty aspects, request-local quality, coalescing, nested draining | Retain |
| Live requests | Slider and handle bursts coalesce; creation feedback loop is fixed | Retain |
| Provisional previews | Planner route can be displayed without persistent publication | Retain |
| Progressive engine | Planner, iteration, contacts, acceptance, and final validation have resumable phases | Complete boundedness |
| Collider set | Planner and solver now share the required collider set with lazy expansion | Retain and test |
| Collision coordinates | Collision calculations operate in world space | Retain |
| Owner contact | Localized authored attachment exemptions exist | Carry identically through all backends |
| Output safety | Provisional/stale results do not feed Fiber Surface, Muscle, Soft Tissue, or mirrors | Retain |
| Caches | Exact, warm-seed, geometry, surface, and factor caches are separated/bounded | Extend signatures |
| Lifecycle | Load/history/cancel/supersede cleanup and token checks exist | Retain |
| Migration | V1 snapshot, atomic V2 commit, failed-migration rollback, Restore Legacy Shape | Retain |
| Native CCD | Windows x64 native swept segment/triangle DLL and Python bridge exist | Qualify and enable for V2 |
| Native packaging | DLL loads through `ctypes`; no end-user C++ executable or compiler is required | Retain |
| Unit contract | New roots can declare 1 world unit = 1 metre; legacy roots remain explicitly undeclared | Retain |
| Telemetry/probe | Per-request phases, solves, iterations, queries, writes, caches, and slices | Extend for V2 residuals |

### 4.2 Partially implemented

| Area | What exists | What is incomplete |
| --- | --- | --- |
| V2 integration | V2 global solve is called from the common solver loop | Its fidelity reference is replaced by the current iterate every iteration |
| Local/global order | Smoothing, collision projection, and acceptance phases exist | They do not yet implement one fixed local/global objective |
| Convergence | Displacement and penetration tolerances exist | Objective stationarity and relative energy progress are ignored |
| Native CCD line search | Opt-in bridge can return a collision-free step | Default is off; invalid-start recovery and qualification remain |
| Multilevel refinement | 8/16/32/64-style levels and weighted iteration splits exist | Work allocation is fixed, not residual-driven |
| Preview publication | Timed progressive preview exists | Raw oscillating iterates/level transitions can still be shown |
| Pure-data contracts | `FiberEngineRequest` and `FiberEngineState` exist | Live sessions still retain Blender RNA, scene, depsgraph, and BVH objects |
| Termination reasons | Internal enum includes precise reasons | Several paths still collapse into budget exhausted/not converged in the UI |
| Determinism | Factor-cache cold/warm output is exact | Iterative warm-seed and cold results differ beyond the desired tolerance |

### 4.3 Known rollout blockers

1. **Incorrect V2 fixed point.** The current integration calls the quadratic solver with the current
   candidate as the fidelity reference on every iteration and discards stationarity. This changes
   the objective every step and makes the result iteration-count dependent.
2. **No production-enabled conservative motion guard.** Native CCD exists but is development-gated.
   V2 cannot be enabled by default until all accepted moving edges use a qualified safe step.
3. **Initially intersecting inputs.** CCD correctly requires a valid start. Stored or newly resampled
   curves that already intersect require explicit depenetration or replanning before CCD may label
   a motion safe.
4. **Contact/local-global integration.** Collision projection targets are local corrections rather
   than auxiliary constraints in a fixed merit formulation.
5. **Weak stopping policy.** The live solve ignores the core stationarity residual and uses absolute
   raw-world tolerances. Fixed iteration splitting can starve the final resolution.
6. **Visible oscillation.** The viewport can show candidates that are subsequently rejected or
   replaced by a safe fallback.
7. **Warm/cold mismatch.** A qualified fixture currently differs by about `2.07e-5`, above the
   approximately `1e-6` scene-scale target.
8. **Deadline overruns.** Atomic collider/BVH work can still produce progressive slices above the
   intended maximum.
9. **Live Blender coupling.** The immutable engine request is not the owner of production numeric
   state, preventing clean numeric isolation and shared multi-Fiber snapshots.
10. **Qualification gap.** There is no unmocked, production-file, successful end-to-end V1-to-V2
    migration proof under all commit gates.

## 5. V2 mathematical contract

### 5.1 Fixed structural objective

For a level with `N` nodes, reference route `q`, hard-pin set `P`, and spacing
`h = 1/(N-1)` for open Fibers or `h = 1/N` for loops:

\[
E_s(x)=\rho\|x-q\|^2+
       \frac{w_L}{h}\|D_1x\|^2+
       \frac{w_B}{h^3}\|D_2x\|^2.
\]

- `q` is captured once when the level starts from the validated planner corridor or compatible warm
  seed. It does not become the previous iterate.
- `D1` controls path shortening/even parameterization.
- `D2` controls curvature.
- `rho` is fixed by engine version, not exposed as an unstable artistic control.
- authored pins are eliminated exactly from the linear system.
- touch pins preserve crossing curvature stencils; they are not hinges.

### 5.2 Collision auxiliary terms

Collision is represented by fixed local constraint slots for nodes and chain edges:

\[
E(x,p)=E_s(x)+\sum_c w_c\|A_cx-p_c\|^2,
\quad p_c\in C_c.
\]

The local step projects the current primitive into its legal clearance set `C_c` and supplies `p_c`.
An inactive constraint uses its current clear target and contributes no correction. The global step
solves the structural/contact compromise. Constraint weights and slot layout are fixed for the
request so the global matrix remains banded and cacheable; only right-hand-side targets change.

The collision set, clearance, owner permission, pin roles, and topology are immutable request data.
Lazy broad-phase activation may reduce work but may not change collision semantics.

### 5.3 Merit and accepted-state contract

Every trial receives a deterministic merit tuple:

1. invalid/nonfinite state;
2. maximum pin violation;
3. maximum clearance violation;
4. total fixed objective/contact energy;
5. normalized stationarity/fixed-point residual;
6. deterministic tie-break hash/order.

Feasibility dominates energy. An infeasible trial may be accepted during explicit initial
depenetration only if it strictly reduces the feasibility violation. After the first valid state,
no accepted state may become invalid.

Native CCD limits movement from the last valid state. A candidate is accepted only when it remains
valid and improves the safeguarded merit. The engine retains:

- current working iterate;
- best validated preview for the current request;
- last committed persistent output.

Only the best validated preview is displayed. Rejected candidates and intermediate resolution
restarts remain internal.

## 6. Correct iteration and convergence policy

### 6.1 Saved iteration fields

`iterations_interactive` and `iterations_bake` remain serialized for compatibility but V2 interprets
them as **maximum accepted-step caps**, not desired work and not stiffness controls. The UI will label
them `Max Iterations (Interactive)` and `Max Iterations (Final)` during the compatibility release.

The engine normally stops much earlier from residuals. A maximum of 1000 remains possible for
diagnostics but must not be required by production examples.

### 6.2 Scale-aware tolerances

At capture time, resolve all raw-world tolerances from:

- scene/root world diagonal;
- `collision_radius` in world units;
- machine epsilon and coordinate magnitude;
- requested quality.

Pin tolerance remains at least `max(1e-7, 1e-6 * scene_diagonal)` unless qualification proves a
tighter stable rule. Clearance and stationarity use normalized residuals so uniformly scaling the
entire fixture, radius, and resolved tolerances produces a uniformly scaled solution.

Root physical-unit metadata controls labels/import compatibility only. It does not silently rescale
legacy geometry or solver coordinates.

### 6.3 Convergence requirements

A level is converged only when all applicable conditions hold:

- exact pins within tolerance;
- exact node and edge clearance within tolerance;
- fixed-objective KKT/stationarity residual below tolerance;
- fixed-point residual below tolerance;
- relative energy decrease below tolerance for a short stable window;
- no unresolved CCD or validator uncertainty;
- active contact set sufficiently stable, or its changes no longer affect the residual.

Small displacement alone is insufficient: it may indicate a blocked line search. Zero penetration
alone is insufficient: the objective may still be far from stationary.

### 6.4 Adaptive multilevel work

The existing coarse-to-fine structure is retained, but work is no longer split by fixed powers of two.

- A coarse level exists to establish route topology and remove large-scale oscillation.
- Promote when feasibility is stable and coarse stationarity has reached its quality target.
- Promote early when further coarse iterations yield little improvement that the finer level can
  represent better.
- Do not promote an unsafe level; depenetrate or replan first.
- Reserve enough total/time budget for the authored final node count.
- Final-quality recompute converges the final level rather than spending a fixed fraction at every
  lower resolution.

Interactive refinement has a soft wall-time budget and continues over resumable slices after quiet
input. Explicit Recompute prioritizes convergence and uses the serialized hard cap. Superseded work
stops immediately and never publishes.

### 6.5 Stagnation classification and recovery

Progress is tracked over a bounded residual/energy window, not by equality within `1e-9`.

| Observed plateau | Recovery | Final reason if recovery fails |
| --- | --- | --- |
| Energy oscillates while feasible | Reset acceleration; reduce relaxation/trust step | `STALLED` |
| Clearance improves but remains positive | Continue depenetration; refresh contacts | `NO_FEASIBLE_PATH` or `BUDGET_EXHAUSTED` |
| CCD safe step repeatedly approaches zero | Replan once; otherwise stop | `BLOCKED` |
| Required collider invalidates planner corridor | Lazy replan with unified set | `NO_FEASIBLE_PATH` |
| Nonfinite objective/candidate | Reject, clear acceleration, use base step | `UNSAFE_OUTPUT` if repeated |
| No remaining energy/feasibility/stationarity progress | Stop truthfully | `STALLED` |

Each expensive recovery is bounded and counted. There is no indefinite retry loop.

## 7. Safeguarded acceleration

### 7.1 Anderson acceleration first

After the unaccelerated fixed map is correct, add Anderson history with initial memory `m=4`:

1. Run at least three accepted unaccelerated local/global steps.
2. Store the last `m` iterates and fixed-point residuals in contiguous arrays.
3. Solve the small least-squares problem for the mixed candidate.
4. Restore exact pin values.
5. Compute collision targets/merit for the accelerated candidate.
6. Apply native CCD from the last valid state.
7. Accept only if the safeguarded merit improves at least as much as the base candidate.
8. Otherwise accept the base candidate and reset or shorten history.

History is reset on:

- request/token, topology, node count, pin mask, weights, or collider generation change;
- multilevel promotion;
- planner/replanner route change;
- large contact-set change;
- rejected/nonfinite accelerated trial;
- initial depenetration mode transition to valid mode.

Memory is O(mN), and the small dense solve is O(m^3 + mN). At Fiber sizes this should be negligible
relative to collision evaluation.

### 7.2 Comparison pilots

Chebyshev acceleration is tested only on clear or contact-stable phases. It is rejected if spectral
estimation, under-relaxation, or contact resets remove its measured advantage.

L-BFGS is tested only if safeguarded Anderson fails the iteration/latency gates. It must share the
same merit and CCD line search; no independent safety path is permitted.

## 8. Collision and path pipeline

### 8.1 Unified collision semantics

Every stage consumes one captured collision policy:

```text
CAPTURE → collider snapshot → planner → exact-count handoff
        → local projections → global solve → CCD acceptance → final validation
```

The planner may begin with spatially relevant colliders and lazily add blockers, but its final route
must be certified against the same required set used by refinement and final validation. Endpoint,
touch, and loop-owner exemptions are local around authored contact; attaching to an SCP never removes
the whole SCP from collision.

### 8.2 Safe exact-count handoff

Resampling a collision-free polyline can create intersecting chords. Therefore:

1. resample by arc length while preserving exact hard-pin order;
2. validate every resulting edge against the unified collision set;
3. insert/refine corridor control where necessary without changing the requested output count;
4. if no safe exact-count representation exists, replan with the node-count/corridor constraint;
5. fail as `NO_FEASIBLE_PATH` rather than starting refinement from a falsely safe seed.

The planner route is a reference corridor and soft objective seed, not final hard geometry.

### 8.3 Invalid-start recovery

Before using CCD, classify the exact initial state:

- valid: enter ordinary V2 local/global iteration;
- locally penetrated but recoverable: run bounded monotone depenetration that must strictly reduce
  exact violation each accepted step;
- planner/resampling invalid: return to planning with newly discovered blockers;
- authored configuration impossible: `INVALID_CONFIGURATION`;
- no feasible route found under bounded search: `NO_FEASIBLE_PATH`.

No invalid start may receive a CCD-safe label.

### 8.4 Native CCD production path

The existing `native/fiber_ccd/af_fiber_ccd.dll` is the Windows development backend. End users do not
install a C++ executable, Visual Studio, CMake, or a service. Release packages ship the compiled DLL.
Only developers rebuilding the DLL require the MSVC/Windows SDK toolchain.

Before default enablement:

- pass adversarial crossing, grazing, coplanar, thin, degenerate, transformed, open, and nonmanifold
  fixtures against the conservative reference;
- verify zero observed misses and requested clearance;
- carry local owner intervals identically into candidate generation and narrow phase;
- fail closed on invalid arguments, uncertainty, budget exhaustion, and invalid starts;
- cache immutable triangle snapshots by collider generation;
- support cancellation/deadline checks between bounded native batches;
- pass clean Blender installation and packaged-DLL loading tests;
- remain materially faster than the Python reference and within the end-to-end latency targets.

IPC Toolkit remains rejected for production unless its dependency, platform, binary-composition, and
license gates change. It is not required to finish V2.

## 9. Pure-data engine completion

### 9.1 Main-thread capture

Blender state is captured once into an immutable `FiberEngineRequest` containing:

- stable request token, root/scene runtime identities, quality, and engine version;
- topology, exact count, symmetry, and resolved world tolerances;
- ordered anchors with point, owner, and endpoint/touch/loop role;
- fixed solver weights and iteration/time caps;
- immutable world-space collider vertices, triangles, bounds, owners, and generations;
- compatible warm seed and validated planner reference;
- all cache-signature components.

After capture, numeric engine code must not access RNA, `bpy`, depsgraph IDs, or `BVHTree`.

### 9.2 Resumable production state

The production state machine owns:

```text
CAPTURE → COLLIDERS → PLAN → LEVEL_SETUP
→ LOCAL_STEP → CONTACTS → GLOBAL_STEP
→ LINE_SEARCH → ACCEPT → FINAL_VALIDATE → DONE
```

Every phase advances bounded node, edge, candidate-pair, or validation batches. Individual native
calls receive bounded pair arrays. A slice stops at its deadline without requiring an entire solver
iteration to finish.

### 9.3 Multi-Fiber SCP synchronization

One runtime request captures one collider snapshot and shares it across all affected Fibers. Work is
scheduled round-robin so one difficult Fiber cannot prevent all others from previewing.

Priority order:

1. selected/actively edited Fiber provisional preview;
2. other visible affected Fiber previews;
3. selected Fiber validated refinement;
4. remaining affected Fibers;
5. downstream committed consumers.

Only committed Fiber generations trigger Fiber Surface/Muscle/Soft Tissue/mirror work. Process-based
parallel baking is considered only after the pure-data engine stabilizes and only if measured
end-to-end speedup is at least 1.8x. No worker accesses Blender data.

## 10. Cache and determinism contract

V2 cache keys include:

- scene/root runtime identity and lifecycle generation;
- Fiber ID plus Fiber revision;
- engine/objective/collision backend versions;
- topology, exact count, symmetry, pin roles/mask, and hinge policy;
- weights, resolved tolerances, quality, and hard caps where output-affecting;
- anchor positions/owners/attachment generations;
- collider geometry/transform generations and required-set identity;
- native backend version and owner-filter policy.

Factor caches contain only immutable factorization data. Warm outputs are seeds, never evidence of
convergence. Exact results replay persisted diagnostics only after independent final revalidation.

Cold solves are deterministic. Compatible warm and cold converged outputs must agree within the
declared scene-scale tolerance. If multiple local minima are intentionally allowed later, the route
corridor/branch identity becomes explicit saved data rather than accidental warm-start behavior.

## 11. Runtime, preview, and UI behavior

### 11.1 Live edit sequence

For handle dragging and solver-property sliders:

1. coalesce input events using the existing quiet-input window;
2. update the authored handle/metadata immediately;
3. retain or display a collision-validated provisional route within one frame;
4. refine progressively without blocking Blender for an unbounded phase;
5. cancel the old token immediately when newer input arrives;
6. publish only improved validated previews;
7. commit once, then trigger downstream consumers once.

The status panel shows both phase and precise termination reason. `Not Converged` is not used as an
umbrella for blocked, unsafe, invalid, superseded, or no-path cases.

### 11.2 New V2 diagnostics

Expose bounded telemetry and optional UI details for:

- level/count and accepted iterations per level;
- base versus accelerated steps and acceleration rejections;
- objective energy components and relative decrease;
- stationarity/fixed-point, pin, node-clearance, and edge-clearance residuals;
- CCD alpha, candidate pairs, tested pairs, and invalid-start state;
- contact-set changes and replans;
- precise termination reason;
- planner/refinement/CCD/final-validation timings;
- maximum/p95 progressive slice duration.

Diagnostics always describe the exact displayed/committed points, never a pre-fallback candidate.

## 12. Ordered implementation stages

Each stage is independently mergeable and leaves V2 rollout disabled until its gate passes.

### Stage 0 — Freeze the current corrected baseline

- Preserve V1 compatibility behavior and the unified planner/solver collider-set regressions.
- Add the recorded oscillating Fiber as a benchmark scenario without modifying the source blend.
- Record one-request token count, level transitions, accepted/rejected iterates, fallback events, and
  final exact diagnostics.
- Add engine-versioned telemetry fields before changing the algorithm.
- Remove any temporary benchmark runners before handoff.

Gate:

- Existing full unit/Blender suites pass.
- Benchmark files remain byte-identical.
- One explicit recompute produces one job/token and no feedback retry request.

### Stage 1 — Correct the V2 fixed objective

- Capture a fixed level reference `q`.
- Add fixed local collision constraint slots/targets.
- Reorder the V2 iteration to local projections → global solve → safe acceptance.
- Preserve crossing bend stencils at touch pins.
- Propagate the core energy and stationarity residual into session state.
- Add dense-reference tests for augmented open/cyclic systems.

Gate:

- With collision disabled, energy is nonincreasing and converges to the direct dense reference.
- Re-running an already converged result does not move it beyond tolerance.
- Length/curvature controls remain distinct and monotonic.
- Warm/cold clear-fixture output agrees within tolerance.

### Stage 2 — Implement truthful adaptive convergence

- Replace equality-based stall detection with progress windows.
- Use pin, clearance, energy, stationarity, and fixed-point residuals.
- Reinterpret iteration fields as caps.
- Replace fixed weighted level allocation with adaptive promotion and a reserved final-level budget.
- Add precise termination/recovery transitions.
- Publish only best validated previews.

Gate:

- The screen-recording fixture no longer visibly oscillates/retries.
- Increasing the hard cap after convergence does not change output materially.
- A feasible 64-node production Fiber normally finishes far below 1000 iterations.
- Blocked and stalled examples never report converged.

### Stage 3 — Finish collision-safe V2 acceptance

- Correct exact-count corridor handoff.
- Implement bounded invalid-start depenetration/replanning.
- Qualify and enable native CCD for every accepted V2 move on Windows.
- Use one localized owner-contact policy in planner, projections, CCD, and final validation.
- Add native static minimum-distance/final-clearance validation or an equivalently independent path.

Gate:

- Zero detected CCD misses in adversarial/reference comparisons.
- Exact final clearance matches requested world radius within tolerance.
- Both mandatory skeleton Fibers follow their complex obstacles without illegal owner exemptions.
- Invalid stored curves recover or fail precisely; none receive a false safe result.

### Stage 4 — Add safeguarded Anderson acceleration

- Implement bounded history and small least-squares solve.
- Compare accelerated and base candidates under the same merit and CCD path.
- Add restart rules for contact, level, planner, and failed-candidate changes.
- Retain a development switch for unaccelerated V2 reference solves.

Gate:

- Representative feasible Fibers require materially fewer accepted steps and lower wall time.
- No accelerated result has worse final merit than the base reference.
- Cold/warm/reference results agree within tolerance.
- Acceleration rejection never causes an unsafe commit or visible regression.

### Stage 5 — Make the pure-data engine production-owned

- Replace Blender-bound live session fields with `FiberEngineRequest` arrays and IDs.
- Cache/share one collider snapshot per runtime request.
- Bound remaining BVH/native batches and final validation to slice deadlines.
- Use fair multi-Fiber scheduling for SCP changes.
- Commit on the main thread only after token/generation checks.

Gate:

- No numeric phase accesses Blender API objects after capture.
- Initialization remains below one frame.
- Progressive p95 is at most 12 ms and maximum below 20 ms on agreed workloads.
- Cancelled/superseded work never publishes or emits solve-ready.

### Stage 6 — Production qualification and rollout

- Run shadow V1/V2 comparison across both supplied files and authored edge cases.
- Add a real, unmocked V1-to-V2 successful migration/rollback workflow.
- Package the Windows DLL and verify clean Blender installation.
- Keep the rollout environment flag until all correctness/performance gates pass.
- Enable V2 by default only for newly created Fibers first.
- Keep legacy Fibers unchanged until explicit Recompute migration succeeds.
- Retain Restore Legacy Shape for the compatibility period.

Gate:

- At least 90% of demonstrably feasible production Fibers converge; every remainder has a precise
  and correct reason.
- No stale/provisional/failed V2 output feeds downstream consumers.
- Migration is atomic under cancellation, source mutation, history change, and validation failure.
- V1 remains available for rollback/comparison during the compatibility release.

## 13. Required tests

### 13.1 Numerical unit tests

- open/cyclic banded factors versus dense reference;
- arbitrary hard-pin masks and touch crossing stencils;
- augmented collision slot matrix and right-hand side;
- fixed reference invariant across iterations;
- energy and stationarity calculations;
- scale equivalence;
- adaptive level promotion and final-budget reservation;
- stall, blocked, unsafe, and budget termination mapping;
- Anderson least-squares, safeguard, restart, and deterministic history;
- factor/exact/warm cache signatures and bounds.

### 13.2 Collision tests

- uniform, nonuniform, mirrored, and negative transforms;
- thin, grazing, coplanar, degenerate, open, closed, and nonmanifold meshes;
- initially valid/invalid curves;
- crossing motion with both endpoints/candidates statically clear;
- exact node and edge clearance;
- endpoint, touch, and loop owner contact with unrelated blockers;
- safe exact-count resampling and impossible corridor representation;
- planner/refinement/CCD/final-validator collision-set parity;
- native/reference pair and composed safe-step comparison.

### 13.3 Runtime/workflow tests

- new Fiber provisional preview and terminal job;
- one physical handle move and no creation-time feedback;
- 20 slider/handle events produce one refinement;
- SCP change shares one collider snapshot and does not multiply requests;
- preview never changes persistent JSON/generation/downstream outputs;
- only improved validated previews replace displayed geometry;
- stale/unsafe output remains unavailable to all consumers and mirrors;
- cancellation, supersede, undo/redo, load, deletion/recreation, and unregister;
- duplicate Fiber IDs in different roots/scenes;
- explicit migration success/failure/replacement/rollback.

### 13.4 Production regressions

- `skeleton_comb_base.blend`: both complex Fibers, their planner corridors, unrelated obstacles,
  owner contact, exact final clearance, and no visible iterative retry;
- recorded `FIBER_1`: 12/30/120/1000 cap comparison and monotone merit trace;
- `skull_muscles.blend`: 24-Fiber interactive SCP synchronization, cold/warm cache behavior, and
  representative 64/256/512-node scaling;
- benchmark hashes checked before and after every run.

## 14. Performance and experience gates

These targets apply on the user's current Windows machine first. Cross-platform expansion is later.

| Workflow | Required gate |
| --- | --- |
| Handle/property event processing | p95 below 5 ms before deferred numeric work |
| Provisional selected-Fiber preview | visible within 16.7 ms when a compatible safe route exists |
| Debounced 64-node selected Fiber | validated commit within 250 ms after quiet input on representative cases |
| Progressive slices | p95 at most 12 ms, maximum below 20 ms |
| Two-Fiber skeleton SCP change | one request, shared snapshot, visibly responsive; target below 200 ms after quiet input |
| 24-Fiber interactive synchronization | below 500 ms stretch target; must first pass below 1 second |
| Representative 512-node solve | below 220 ms |
| Fixed-work 256→512 scaling | below 2.4x |
| Native CCD | zero detected misses and materially faster than reference; owner filtering below 20% overhead |
| Telemetry overhead | below 2% |

Correctness gates take precedence. A faster unsafe curve fails.

## 15. Compatibility and data policy

- `FiberSolver`, `solve_points`, `clear_cache`, progressive entry points, result fields, route strings,
  and `FIBER_SOLVE_READY` remain compatible.
- `solver_version`, `collision_radius`, length/bend saved fields, import/export, and legacy snapshots
  remain additive.
- V1 values remain serialized; V2 labels them `Length Weight` and `Curvature Weight`.
- `thickness` remains display-only; `collision_radius` remains the world-space collision control.
- Existing files do not solve on load.
- Existing V1 Fibers retain stored shapes until explicit migration.
- Legacy unit metadata may remain undeclared; no coordinates or radii are silently converted.
- Cross-root import never auto-scales geometry. Physical labels require a declared/calibrated root
  contract, but raw-world V2 solving remains possible without calibration.

## 16. Risks and decisions

| Risk | Response |
| --- | --- |
| Contact projections make the map nonsmooth | Safeguarded base step, contact-aware Anderson resets, native CCD |
| Acceleration converges to a different branch | Fixed planner corridor/branch identity and merit; cold reference mode |
| Invalid stored starts cannot use CCD | Explicit depenetration/replanning state before safe motion |
| Owner exemption hides deep intersections | Author-contact bounded intervals and independent final validation |
| Exact-count resampling destroys a safe route | Corridor-aware handoff and replan/fail before refinement |
| Native DLL portability | Windows first; packaged binary; backend interface remains replaceable |
| Native call exceeds slice deadline | Bounded candidate-pair batches and cancellation checks |
| Energy evaluation adds collision cost | Reuse local projections/queries; compare base and accelerated candidates selectively |
| Warm start changes result | Warm seeds never imply convergence; cold qualification and fixed route identity |
| Legacy scale is physically unknown | Raw-world numerics; explicit unit calibration only for physical claims/import checks |

## 17. Explicit non-goals

- Do not port the V1 duplicate-Laplacian loop to C++.
- Do not call a larger fixed iteration count an optimization.
- Do not weaken final validation to improve convergence statistics.
- Do not commit a visually acceptable but collision-unsafe candidate as CURRENT.
- Do not use Python threads for Blender API work.
- Do not adopt full IPC, XPBD, a GPU framework, or a physical rod model without a new product decision.
- Do not optimize planner graph construction until it exceeds 15% of post-V2 end-to-end time.
- Do not move stabilized numeric work further into native code until the fixed objective and acceptance
  semantics pass reference tests.

## 18. Definition of V2 complete

V2 is complete when all of the following are true:

1. It minimizes one documented fixed static centerline objective with independent length and
   curvature controls.
2. Hard pins, exact count, world-space clearance, and local owner contact are correct and independently
   validated on the exact committed points.
3. Native conservative motion protection is enabled for every V2 accepted step on the supported
   Windows release.
4. Adaptive convergence normally stops far before the hard iteration cap and correctly identifies
   converged, stalled, blocked, unsafe, invalid, and no-path cases.
5. Safeguarded acceleration reduces iterations/wall time without changing the qualified result or
   safety.
6. The viewport never displays rejected oscillating iterates as progress; it retains the best
   validated preview and last committed result separately.
7. The production engine is pure data after capture, resumable, cancellable, deterministic, and
   deadline-bounded.
8. Handle dragging, property editing, and multi-Fiber SCP synchronization pass the agreed live-edit
   gates on the user's machine.
9. Both supplied production files pass geometry, collision, convergence, migration, cache, and
   performance qualification without being modified.
10. New Fibers default to V2 only after these gates pass; legacy migration remains explicit and atomic.

Until then, V2 remains opt-in/shadow-only and the corrected V1 compatibility path remains available.

Package 1 — Pure V2 contracts
Create only plain-data types:
V2Request
V2Result
V2Settings
V2Diagnostics
V2Termination
resolved tolerance and collision-policy records
Requirements:
NumPy/plain Python only.
No bpy, RNA, depsgraph, BVHTree, visualization or persistence.
Stable request signatures and engine versions.
Gate: contract and serialization tests pass. Zero V1 files changed.
Package 2 — Structural mathematical core
Implement the collision-free objective:
\[
\rho\|x-q\|^2+\frac{w_L}{h}\|D_1x\|^2+
\frac{w_B}{h^3}\|D_2x\|^2
\]Includes:
open pentadiagonal solver;
cyclic Woodbury correction;
exact hard-pin elimination;
independent length and curvature weights;
fixed planner reference q.
Gate:
Dense-reference parity.
Open/cyclic tests.
Exact pins.
Monotonic, distinct controls.
Re-solving a converged result does not move it.
This follows the prefactorized local/global approach from Projective Dynamics.
Package 3 — Standalone native collision backend
Develop and test collision independently from the solver:
immutable triangle snapshot;
static node/segment minimum distance;
swept segment/triangle CCD;
conservative safe-step fraction;
localized owner-contact filters;
invalid-start reporting;
chunked native calls.
Gate:
Zero misses against brute-force adversarial references.
World-transform equivalence.
Thin, grazing, coplanar and degenerate tests.
Missing/incompatible DLL returns BACKEND_UNAVAILABLE.
No end user compiler is required.
Package 4 — V2 planner and exact-count handoff
Standalone inputs: anchors, node count, collider snapshot and policy.
Outputs:
deterministic route branch;
exact-count planner reference q;
hard-pin indices;
validated corridor;
NO_FEASIBLE_PATH when necessary.
Tests cover:
sphere fanning;
skull zigzags;
rib-cage routing;
unrelated colliders;
unsafe resampling chords;
complex touch ordering.
Gate: every produced edge passes Package 3 validation.
Package 5 — Unaccelerated local/global solver
Combine Packages 2–4 without Blender integration:
project active contacts;
solve the banded global system;
evaluate merit;
apply CCD-limited acceptance;
independently validate the accepted state.
Important:
q stays fixed.
Warm starts change only the initial iterate.
Once valid, an accepted state cannot become invalid.
No Anderson acceleration yet.
Gate:
Warm/cold agreement.
Nonincreasing accepted merit.
Exact final validation.
Deterministic output.
Complex skeleton fixtures no longer penetrate ribs.
Package 6 — Adaptive convergence
Add:
normalized fixed-point residual;
stationarity residual;
relative energy decrease;
adaptive node levels;
final-level budget reservation;
precise CONVERGED, STALLED, BLOCKED, NO_FEASIBLE_PATH, UNSAFE_OUTPUT and BUDGET_EXHAUSTED.
Gate:
The recorded Fiber does not require 1000 iterations.
Raising the cap after convergence does not change its result.
No visual retry logic is involved—this remains pure-data testing.
Package 7 — Optional Anderson acceleration
Implement as a removable wrapper around Package 5.
Default off.
Memory m=4.
Accelerated proposal must beat the base proposal.
Same CCD and validator.
Immediate fallback to the base step when rejected.
Gate:
Faster than the unaccelerated reference.
Same final result and feasibility.
If it fails the gate, discard this package without affecting V2.
The safeguard follows the energy-decreasing approach from Anderson Acceleration for Geometry Optimization.
Package 8 — Read-only Blender shadow adapter
First Blender integration, but no visual or persistent changes.
Capture one immutable V2 request on the main thread.
Run V2 in shadow beside normal V1.
Record differences, timing and diagnostics.
Never display, persist or publish V2 output.
Gate:
V1 output and behavior remain bit-for-bit unaffected.
Supplied production files can be benchmarked safely.
Package 9 — Explicit V2 preview
Only Fibers explicitly marked development V2 use this path.
Immediate provisional preview.
Validated V2 preview replaces it.
Failed result remains visible as FAILED_PREVIEW.
No snapping to old geometry.
Preview never reaches Muscle, Surface, Soft Tissue or mirrors.
V1 preview code remains unchanged.
Gate: handle and property interactions behave correctly under success, failure, cancellation and superseding edits.
Package 10 — Explicit migration
Add the V1→V2 Recompute workflow:
save legacy snapshot;
calculate V2 independently;
commit atomically only on success;
retain V1 shape and version on failure;
Restore Legacy Shape remains available.
New Fibers still default to V1.
Package 11 — V2 scheduling and performance
Only after correctness:
shared collider snapshot for SCP changes;
round-robin Fiber sessions;
selected-Fiber priority;
bounded progressive slices;
cancellation by request token;
downstream execution only after validated commits.
No downstream component may synchronously request another Fiber solve.
Package 12 — Qualification and rollout
Run:
all supplied files;
complete Blender suite;
real migration success/failure;
clean Blender DLL packaging;
24-Fiber and 512-node benchmarks;
convergence and collision qualification.

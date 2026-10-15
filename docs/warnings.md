# File warnings and authoring feedback

AF-20 provides one Python-only warning repository for all AnthroForge roots in
all loaded scenes. Nothing in this repository is saved in a blend or a request
receipt. The sidebar's first section, **File warnings (N)**, counts findings
(one pin/blocking-owner pair), not distinct pins. Its scrollable list selects
the offending endpoint A/B, authored middle touch, or authored loop anchor.
Generated symmetry pins are not checked as authored controls.

The initial provider is `fiber_hard_anchor.v1`, code
`FIBER_INVALID_HARD_ANCHOR`. It uses the same native contact kernels as
production preflight, with the same owner skip, ancestry evidence, clearance
slack and containment policy. Clear pin preflight does not certify a usable
route. Overlap/escape checks are separate work (AF-21).

## Query and mutation feedback

All supported protocol versions (0.2.0, 0.3.0, 0.4.0) accept:

```json
{
  "version": "0.4.0",
  "message_type": "request",
  "request_id": "pins-1",
  "op": "warnings.list",
  "params": {"scene_id": "AF_ROOT", "limit": 100, "offset": 0}
}
```

`scene_id` is the normal authoring envelope context; the default warning query
is deliberately file-wide. Optional `scene` and `root` filters are runtime
identity tokens from warning references, not display names. Other filters:
`entity` (native ID), `kind`, `code`/`type`, and `authoring_id`.
Offset is nonnegative, limit is 0–200. Use limit 0 for status/count only.

`response.warnings` includes `epoch`, `repository_revision`, `check_token`,
`scope`, `total`, `records`, `complete`, `discovery`, per-state `counts`,
`failures`, `source_generations`, and `telemetry`. The source scene revision
is explicitly `unavailable` when no verified current authoring digest is
available; source generations, not an old authoring digest, identify checks.
Check tokens are opaque polling/version tokens, not completion promises.

Each record contains a semantic stable ID, provider/version, code, severity,
summary, corrective details, numerical evidence (owner, blocker, relation,
world point, configured/effective/measured clearance, residual, containment),
entity reference, optional pin reference, related owners and source generation.
Entity references carry file epoch, scene/root identity and current capture
labels, native ID, kind and PropertyGroup incarnation. Native authoring writes
also retain their authoring entity ID for mapping back to the recipe.
Pin references carry exact role/index plus attachment revision and fingerprint.
Touch index is the authored route index (collection index + 1); loop indices
are zero based. Warning selection verifies these identities before navigation.

For example, after a native authoring update creates an invalid midpoint:

```json
{"status":"success","warnings":{"complete":false,"total":0,"check_token":"epoch:41","counts":{"PENDING":1}}}
```

This is an abbreviated response, not a clean result. Poll `warnings.list`;
once `complete` is true, a representative finding is:

```json
{"code":"FIBER_INVALID_HARD_ANCHOR","pin":{"role":"TOUCH","index":1,"attachment_revision":2,"fingerprint":"..."},"evidence":{"owner_id":"SCP_1","blocker_id":"SCP_2","relation":"UNRELATED","contained":true}}
```

Correct the midpoint using the normal authoring update/route-override API.
Its response again says pending. Poll until completion:

```json
{"warnings":{"complete":true,"total":0,"records":[],"check_token":"epoch:49"}}
```

Only the last state confirms that the checked warning scope is clear. It does
not certify the route, solver result, anatomical validity, or downstream mesh.
Warnings never change the command's success/unresolved/failure semantics.
Final responses, including cached request replay and rollback/partial errors,
receive live warning feedback after persisted response construction, so saved
receipts cannot masquerade as current validation. A cached mutation replay
does not itself rerun diagnostics; it returns the live repository token.

## Runtime and lifecycle

One main-thread coordinator dispatches registered providers' `check_all` and
`on_action`. Runtime completion emits normalized dirty/propagated entity sets.
SCP changes conservatively invalidate all root Fibers because unattached SCPs
can block pins. Import, authoring, repair and structural edits have explicit
invalidation boundaries. Selection-only events do not schedule checks.

Load/history pre clears findings, retires incarnations, rotates the file epoch
and cancels queued work. Post events schedule rediscovery. Enabling on an open
file also schedules checks; unregister unsubscribes, cancels, and closes the worker.
Root membership changes are reconciled through the existing depsgraph lifecycle.
Each new root edit restarts a 150 ms debounce. Capture and publication run on the
main thread with at most 128 cooperative steps and a 4 ms soft budget per tick.
An individual evaluated mesh capture can exceed that budget; `max_tick_ms`
reports the actual duration. Collider snapshots reuse the production capture
cache. A root index resolves attachment owners once per scan.

`warning_pipeline` owns capture, submission and publication. `Coordinator` owns
generation tokens, debounce and polling deadlines. `NativeWarningExecutor`
exposes submit/poll/read/cancel/release operations through the packaged C++17
library (`af_fiber_ccd_v3_28.dll`, warning ABI 1). Submission copies mesh arrays,
world-space anchors, owner tokens and clearances before returning. The worker
builds a private collision world and evaluates the snapshot without Python
callbacks or Blender references. It does not share the solver's mutable world.
Cancellation sets an atomic flag without joining. The main-thread timer reaps
finished cancelled jobs; unregister joins before destroying the executor.
Missing native support fails explicitly.

Generation checks prevent older root scans from publishing over newer actions;
successful empty results reconcile only the checked provider/entity. Failed,
unresolved or cancelled scopes remain non-clean. Records retained while checks
are pending/failed are explicitly stale. UI draw, queries and selection never
evaluate collisions, repair geometry, or begin planner/solver sessions.

The RNA list stores warning tokens only, is cleared before save/load, and is
rebuilt from Python state after save. It is not authoritative, even if a Blender
version restores WindowManager properties. Fiber warning payloads are regenerated;
the generic artifact subsystem restores persisted evidence as stale, as described below.
Repository notifications are batched per scheduler tick; queries still see each
state change immediately. Progress refreshes are coalesced to 100 ms, and an
unchanged token list does not rewrite RNA rows. Completion refreshes immediately.
Telemetry includes elapsed/max tick time, checked entities/pins, captures/cache
hits, incrementals, coalescing, cancellations, stale rejections and failures.
`native_submit_ms` measures main-thread snapshot submission and
`native_worker_ms` measures completed background jobs. These overlap wall-clock
time and must not be added as an independent user-visible delay.

Blender references: [Application handlers](https://docs.blender.org/api/current/bpy.app.handlers.html),
[Python threading limitations](https://docs.blender.org/api/main/info_gotchas_threading.html).


## Generic issue system and stage progression

`core.issues` contains the generic repository, reporting facade, registered listener
scheduler, presentation projection, and explicit solver registry. Domain adapters
live outside it. `core.warnings` remains a compatibility port for existing fiber
callers and authoring `warnings.list`; it shares the same repository, not a second
copy. Public module registration/reporting is available through `core.issues.api`.

Use `system().reporting.begin_check(target.scope, producer)` and
`complete_check(ticket, issues)` to reconcile a producer's entire checked scope.
Failure/cancellation retains previous evidence as stale. Generation tickets and the
session epoch reject old results. `report(issue)` adds a direct finding without
running a detector. Issue identity includes target incarnation, producer, stage,
artifact revision, code and producer-local key. Completing one producer never
removes another producer's findings.

Register listeners with `register_listener`, solvers with `register_solver`, and
selection adapters with `register_target`. Listener jobs use provider-scoped keys
and the existing debounced main-thread scheduler. Solvers provide applicability,
invocation and optional polling/cancellation. Reporting, queries and drawing never
invoke a solver. The first solver is the existing **Repair Fibers (whole root)**
command, including its existing risky-change confirmation. Fix completion requests
a fresh detector check; dismissal only hides a row for its current artifact revision.

The warnings panel filters cached records and shows producer, stage, freshness and
evidence. Select, Recheck, Dismiss and applicable Fix actions use the generic ports.
Artifact rechecks capture Blender arrays on the main thread and run read-only
native diagnostics off-thread. Loading/undo restores persisted artifact evidence
as stale and does not regenerate geometry. Older meshes without reports are
unknown; reading an output no longer fabricates passing validation flags.

### Skin and topology policy

Quality findings are warnings: protected-gap violations, exposed/crossed source
geometry, pre-existing source intersections, disconnected components, non-watertight
or inconsistent orientation, geometric degeneracy, high valence, guide/boundary,
symmetry, fidelity or quad-budget deviations, and update/inversion quality findings.
A quality warning alone does not request a topology rebuild. The result's validation
report remains available and may be false even when publication succeeds.

Actual consumer requirements still block: missing or malformed arrays, nonfinite
positions, invalid indices, no usable nonzero-area surface, unavailable required
native code, failed allocation without an output, missing required update bindings,
or changed vertex identities/connectivity for an update that requires fixed topology.
Newly generated meshes can be published without usable update bindings; the binding
failure is reported and a later binding-dependent consumer must rebuild/rebind or stop.
Explicit cancellation prevents publication of unfinished jobs.

Native intersection diagnostics use a bounded BVH traversal, at most 256 stored
witness pairs, a memory preflight, a pair-work limit and cancellation. Proper
crossings and contact-only pairs are reported separately. Quad checks use diagonal
0–2 tessellation, so they are not interchangeable with Blender's chosen tessellation.
An optional diagnostic failure means **quality unknown**, never a clean result.

Coordinated worker protocol 4 checkpoints completed skin/topology stages atomically.
A topology failure after completed skin returns `PARTIAL`: publish skin, retain the
previous topology marked stale and keep its bound skin as a referenced mesh datablock
without another visible object. The reference persists through save/reopen and is
used by subsequent update capture. Cancellation retains checkpoint files for diagnosis
without publishing them. Publication also rejects a changed source epoch/revision.
Skin/topology array protocol 5 adds issue metadata; readers accept previous supported
array versions. New job protocols reject incompatible worker generations.

Tests: `test_issue_system`, `test_mesh_issues`, existing warning/scheduling tests,
`test_issue_system_integration`, and existing warm/topology integration tests.
`tools/issue_system_acceptance.py` exercises the actual torso fixture, Root Y,
initial topology and the real Ribs Top Radius +2% update, saving a debug copy.

The October 14 torso acceptance run preserved the update's 7,350 quads and their
exact connectivity. Native checks reported 149 crossings in the updated skin and
1,090 in the updated topology. These findings remained visible warnings while
the update completed; this validates progression, not collision-free geometry.
The debug copy was reopened with 124 visible fibers and 22 native-colored SCPs.

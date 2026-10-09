# Runtime Contract

This document freezes the runtime contract used by the dependency runner before any call-site refactor.

## Entry Points

- `core.visualization.sync_runner.sync_from_dirty_hints()`
- `core.visualization.sync_runner.schedule_sync_from_dirty_hints()`
- `core.deps.runtime.run_dependency_runtime()`
- `core.deps.runtime_intents.dispatch_runtime_intent()`

## Runtime Request Shape

Every runtime request carries the same fields:

- `root`: add-on root object.
- `scene`: Blender scene that owns the root.
- `dirty_hints`: entity ids by type, using `SCP`, `FIBER`, `FIBER_SURFACE`, `MUSCLE`, `SOFT_TISSUE`, and `BLOB` keys.
- `bake`: boolean that controls bake-sensitive sync work.
- `source`: origin of the request such as `operator`, `property`, `depsgraph`, or `manual`.
- `event_type`: semantic event label such as `UPDATE`, `DELETE`, `MARK`, `IMPORT`, or `TRANSFORM`.
- `payload`: extra runtime metadata forwarded unchanged into `gate_meta`.
- `full`: explicit full-runtime intent. Targeted requests set this to `false` even when no target resolves.
- `dirty_aspects`: semantic changes by entity type, such as Fiber `SOLVER`, `ATTACHMENT`, or `RELATIONSHIP`.
- `quality`: request-local `INTERACTIVE` or `FINAL` quality. `bake` remains a compatibility alias for `FINAL`.

## Payload Keys

The current payload contract includes these keys:

- `scp_recapture_ids`: SCP ids that must recapture attachment data before sync.
- `scp_apply_target_ids`: SCP ids whose own attachments must solve against their current parents.
- `scp_apply_parent_ids`: SCP ids whose child attachments must be re-applied during sync.
- `non_source_ids_by_type`: entity ids that are dirty side effects and must not seed source-start traversal.

## Queue Semantics

`schedule_sync_from_dirty_hints()` stores runtime work in the in-memory `_PENDING` queue in `core/visualization/sync_runner.py`.

- Queue items persist `scene` and `root` by name and resolve fresh RNA objects at flush time.
- Compatible depsgraph `SCP_UPDATE` transform requests coalesce by scene/root/source/event so the latest Blender state wins.
- Compatible property `FIBER_UPDATE` requests coalesce over a 125 ms quiet window and union dirty ids and aspects.
- Coalesced SCP requests merge `dirty_hints`, `scp_recapture_ids`, `scp_apply_target_ids`, `scp_apply_parent_ids`, and `non_source_ids_by_type`.
- Deferred SCP requests carry `first_seen_at` and `due_at`; `_TIMER_DUE_AT` tracks the currently armed Blender timer deadline.
- `_arm_timer()` registers exactly one Blender timer while `_TIMER_ARMED` is true, rearming when the queue's earliest deadline moves earlier or later.
- `_flush_pending()` runs one due request, returns a float for the next due item, and returns `None` only when the queue is empty.
- Nested synchronous requests enter a bounded tail queue. Four tail passes run before any remainder moves to the timer queue.
- `AF_DEPS_DEFER=0` disables debounce; `AF_DEPS_DEFER_MS` tunes the SCP quiet delay; `AF_FIBER_DEFER_MS` tunes the Fiber quiet delay; `AF_DEPS_DEFER_MAX_MS` optionally caps continuous deferral when set above zero.
- `load_pre`, `undo_pre`, and `redo_pre` clear queued work before history changes replace RNA data.

## Runtime Traversal Rules

- `dirty_hints` is normalized against the runtime entity sets.
- Legacy absent or plain-empty hints still request a full pass for compatibility.
- `empty_dirty_hints()` marks intentional full requests; `dirty_hints_for()` marks targeted requests.
- A targeted request whose ids no longer exist is a no-op and never escalates to a full pass.
- `non_source_ids_by_type` removes side-effect ids from the source-start set but does not remove them from the impacted sync set.
- `source`, `event_type`, and `payload` are forwarded into `gate_meta` unchanged.
- The runtime adds `runtime_dirty_ids_by_type` after dirty normalization. Drivers use it to distinguish authored entity inputs from downstream attachment-derived impacts; it is not a caller payload key.
- Direct Controlled Fiber `input` mutations use the Fiber engine. SCP attachment edges target `FIBER.attachment_world`; unchanged SCP-only derived changes retain the existing attachment-wave path.

## Mixed surface dependencies

Roots with muscle-backed fibers execute geometry consumers in deterministic
topological waves. Structural typed parents, node influences, additional supports
and active stacking relationships contribute dependency edges. Assign/Rebind and
support mutations validate acyclicity before committing. SCP attachment waves
remain a separate existing driver.

Required source/mirror publications precede dependent fibers, their Fiber
Surfaces and volumes. Readiness is `CURRENT`, pending, or invalid/stale, with a
reason and generation. An asynchronous native or stacking job is a publication
barrier; its final notification resumes affected dependents. Superseded requests
cannot commit against a newer generation. A failed reroute is not retried for the
same parent generation. Free collision failures never invoke automatic routing.

Typed fiber payload version 3 retains barycentric triangles, topology signatures,
frame offsets and blend weights. Versions 1/2 remain readable without implicit
recapture. New signatures describe connectivity rather than deformation-sensitive
quad triangulation. Ordinary resolution never substitutes another triangle.
Attachments Enabled and manual tissue updates retain their existing gates.
Decoded binding payloads are immutable and cached by their complete serialized
content (128 entries, at most 256 KiB per cached payload). Each attachment wave
captures fresh surface identity, topology and generation checks; the decode cache
does not cache publication readiness or resolved geometry.

## Refactor Constraint

Later phases may wrap this contract, but they must preserve the request fields, payload keys, targeted-empty semantics, deferred merge behavior, bounded nested tail, and gate metadata semantics until parity tests are updated on purpose.

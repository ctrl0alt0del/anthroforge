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
- `dirty_hints`: entity ids by type, using the `SCP`, `FIBER`, `MUSCLE`, and `BLOB` keys.
- `bake`: boolean that controls bake-sensitive sync work.
- `source`: origin of the request such as `operator`, `property`, `depsgraph`, or `manual`.
- `event_type`: semantic event label such as `UPDATE`, `DELETE`, `MARK`, `IMPORT`, or `TRANSFORM`.
- `payload`: extra runtime metadata forwarded unchanged into `gate_meta`.

## Payload Keys

The current payload contract includes these keys:

- `scp_recapture_ids`: SCP ids that must recapture attachment data before sync.
- `scp_apply_target_ids`: SCP ids whose own attachments must solve against their current parents.
- `scp_apply_parent_ids`: SCP ids whose child attachments must be re-applied during sync.
- `non_source_ids_by_type`: entity ids that are dirty side effects and must not seed source-start traversal.

## Queue Semantics

`schedule_sync_from_dirty_hints()` appends a request to the in-memory `_PENDING` queue in `core/visualization/sync_runner.py`.

- Requests stay FIFO.
- `_arm_timer()` registers exactly one Blender timer while `_TIMER_ARMED` is true.
- `_flush_pending()` pops one request, calls `_run(**request)`, and returns `0.0` to keep draining the queue.
- `_flush_pending()` returns `None` only when the queue is empty, and that transition clears `_TIMER_ARMED`.
- `_RUNNING` prevents re-entrant execution inside `_run()`.

## Runtime Traversal Rules

- `dirty_hints` is normalized against the runtime entity sets.
- If normalization produces no matching ids, runtime falls back to a full pass.
- `non_source_ids_by_type` removes side-effect ids from the source-start set but does not remove them from the impacted sync set.
- `source`, `event_type`, and `payload` are forwarded into `gate_meta` unchanged.

## Refactor Constraint

Phase 2 and later may wrap this contract, but they must preserve the request fields, payload keys, FIFO timer behavior, and gate metadata semantics until parity tests are updated on purpose.

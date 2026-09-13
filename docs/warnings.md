# File warnings and authoring feedback

AF-20 provides one Python-only warning repository for all AnthroForge roots in
all loaded scenes. Nothing in this repository is saved in a blend or a request
receipt. The sidebar's first section, **File warnings (N)**, counts findings
(one pin/blocking-owner pair), not distinct pins. Its scrollable list selects
the offending endpoint A/B, authored middle touch, or authored loop anchor.
Generated symmetry pins are not checked as authored controls.

The initial provider is `fiber_hard_anchor.v1`, code
`FIBER_INVALID_HARD_ANCHOR`. It calls the same AF-6 collision evaluator as
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
file also schedules checks; unregister unsubscribes and cancels. Root membership
changes are reconciled through the existing depsgraph lifecycle. Work captures
one collider or anchor per cooperative step and checks at most 32 anchors per
collision call. A tick permits at most 32 steps with an 8 ms soft budget.
Single-object evaluated mesh capture or native collision-world construction can
exceed that soft budget; `max_tick_ms` exposes the actual duration. Captured
colliders/native worlds reuse production numerical caches.

Generation checks prevent older root scans from publishing over newer actions;
successful empty results reconcile only the checked provider/entity. Failed,
unresolved or cancelled scopes remain non-clean. Records retained while checks
are pending/failed are explicitly stale. UI draw, queries and selection never
evaluate collisions, repair geometry, or begin planner/solver sessions.

The RNA list stores warning tokens only, is cleared before save/load, and is
rebuilt from Python state after save. It is not authoritative, even if a Blender
version restores WindowManager properties. Load never restores warning payloads.
Telemetry includes elapsed/max tick time, checked entities/pins, captures/cache
hits, incrementals, coalescing, cancellations, stale rejections and failures.

Blender lifecycle reference: [Application handlers](https://docs.blender.org/api/current/bpy.app.handlers.html).

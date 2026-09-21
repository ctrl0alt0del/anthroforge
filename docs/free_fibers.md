# Controlled and Free fibers

Controlled fibers use the existing routing planner and solver. Free fibers store
an explicitly authored sampled path and never request either. Both modes retain
the existing SCP attachment deformation. Behavior is independent of OPEN/LOOP
topology, symmetry and solver version. Legacy files and human creation methods
default to Controlled.

## Editing in Blender

1. Select a native fiber and switch **Behavior** to **Free**. Conversion freezes
   the last committed route exactly; it ignores a transient solver preview. A
   missing or ambiguous committed structural sample rejects conversion without
   launching a solve.
2. After skeletal changes, choose **Edit Path**. The draft contains the current
   attachment-deformed samples as exact POLY curves, one open spline per span
   between structural points. A LOOP includes its closing span. No fit, smoothing
   or resampling occurs when opening the editor.
3. Use native curve tools to move, insert or delete interior points. Keep each
   span's endpoints at the shared attachment positions. **Apply** validates and
   commits the entire path, captures fresh attachment frames and updates outputs
   atomically. **Cancel** discards the draft. An unchanged POLY draft causes no
   attachment recapture or path rewrite.

The Fiber panel follows both a directly selected source and its active draft;
an older SCP/tree selection does not hide Apply or Cancel. Editor objects carry
dedicated `af_free_editor_*` ownership, never native fiber-proxy ownership.
Each scene owns its editor collection. Opening a draft restores that collection's
visibility in the active view layer; failed opening removes every partial span.

**Convert to Bézier** creates one VECTOR-handle knot per POLY vertex, preserving
the starting shape. **Sampling Resolution** controls explicit Bézier evaluation
and **Resample Preview**, not an ordinary POLY Apply. Resampling is a deliberate
preview and can change unbound corners. All structural tags remain exact.
Bézier knots/handles become sampled geometry on Apply; sparse handles are not a
persistent deformation model. The saved Controlled `node_count` is independent
of Free sample count.

Changing the skeleton, root transform, bindings, topology, symmetry, path or
publication authority makes an open draft stale. Apply refuses to overwrite the
new state. **Refresh** opens the current path; **Rebase Preview** transfers the
old draft displacement onto the current span by normalized arc length. Both
retain the prior draft for recovery. Rebase still requires explicit Apply.
Replacement spans are staged before the prior session is removed. Allocation,
rebase or persistence failures retain the original raw curve, session and recovery
history unchanged; no partial replacement becomes authoritative.
Changed structural order requires preserving/discarding the old draft before
opening another session.

Mode changes require Apply or Cancel first. Switching back to Controlled uses
the original routing anchors and saved solver settings. A failed solve retains
the previous valid geometry and reports the solver failure. Free samples never
become routing midpoints automatically.

Save records the raw draft without applying it. Load, undo and redo reconcile
ownership and restore open drafts as stale. Native Edit Mode undo changes the
draft; Apply is one committed undo step. Unregister saves recoverable draft data
and removes live editor objects/handlers. Deleting a native fiber removes its
owned session; deleting a draft does not delete its native fiber.

Unsupported extra splines, changed cyclic flags, joined/split spans, modifiers,
constraints and singular transforms reject Apply and preserve the draft.
Converting a draft to Mesh also rejects Apply; Cancel still removes every owned
span and its unused data through Blender's type-aware datablock removal.

## Authoring protocol 0.4

Capability: `free_fibers.v1`. Call
`app.authoring.api.execute(request, root, scene, journal_directory)` using the
closed [protocol schema](../core/authoring/schemas/protocol-0.4.schema.json).
All requests use `version: "0.4.0"`, `message_type: "request"`, a unique
`request_id`, `op` and `params.scene_id` (the native root name).

| Operation | Additional required parameters |
| --- | --- |
| `fibers.create_controlled` | `expected_scene_revision`, ordered `attachments` |
| `fibers.create_free` | `expected_scene_revision`, ordered `attachments`, `path` |
| `fibers.path_inspect` | `fiber_id` |
| `fibers.path_update` | `fiber_id`, `expected_scene_revision`, `expected_path_revision`, `path` |
| `fibers.mode_configure` | `fiber_id`, `expected_scene_revision`, `expected_path_revision`, `mode: "FREE"` or `"CONTROLLED"` |

Creation accepts optional `name`, `topology` (`OPEN` default or `LOOP`) and
`settings`. Allowed settings are `node_count`, `solver_version`,
`iterations_bake`, `collision_radius`, `thickness`, `use_surface_routing` and
`use_segment_collisions`. Free creation sets its mode before any synchronization.

Attachments are ordered START, MID..., END for OPEN (at least two), or LOOP
anchors for LOOP (at least three). An existing shared point uses only
`{"point_id": "existing-id"}`; its binding is authoritative. A new point supplies
`point_id`, native `parent_id` and `attach_param`, with optional `normal_offset`.
Bindings must qualify at their exact retained positions. Shape samples may keep
offsets from bone surfaces; capture does not project the entire curve onto bone.

A POLY path has the following form. Coordinates and IDs below illustrate the
contract; obtain valid attachment positions from the current scene.

```json
{
  "representation": "POLY",
  "space": "WORLD",
  "samples": [
    {"sample_id": "s0", "co": [0, 0, 0]},
    {"sample_id": "s1", "co": [0.5, 0.2, 0.1]},
    {"sample_id": "s2", "co": [1, 0, 0]}
  ],
  "structural": [
    {"occurrence_id": "o0", "point_id": "origin", "sample_id": "s0", "role": "START"},
    {"occurrence_id": "o1", "point_id": "insertion", "sample_id": "s2", "role": "END"}
  ]
}
```

`space` is `WORLD` or `ROOT_LOCAL`. For Bézier input, use
`representation: "BEZIER"`, replace `samples` with `knots` (each has `sample_id`,
`co`, `handle_left`, `handle_right`) and provide integer `resolution`. Every knot
and structural endpoint is retained; insufficient sample budgets reject the
request. A LOOP does not duplicate its first sample at the end.

`path_inspect` returns `behavior_mode`, `path_revision`, `geometry_sample_count`,
`controlled_node_count`, `attachment_error`, `path` and `points_world` in its
entity. **`points_world` is the currently deformed geometry.** `path.samples`
stores coordinates at the latest authoring capture in root-local space. When
editing after deformation, pair the current points with the stored sample IDs
and structural tags. Do not reuse old capture coordinates as the visible path.
Controlled inspection has no Free payload and returns its committed points.

Path updates retain the entire existing ordered `structural` list, including
sample/occurrence IDs. Unbound samples may be inserted or removed. Use
`points.edit` for a deliberate bound-point move; incident Free spans receive a
deterministic cubic smoothstep displacement between neighboring anchors, then
recapture current attachments. Unchanged spans remain unchanged. Shared branch
children retain the shared binding/offset with independent incident tangents.

UI and authoring use the same atomic validation/capture/publication service.
Failed geometry, binding, budget or journal writes roll back native records and
generated output. Explicit commits verify dependent surfaces, branched assemblies,
base/inflated meshes and derived mirrors inside the transaction. Failed output
evaluation restores geometry and runtime status and retains the UI draft.
Mirror matrices use an absolute `1e-6` verification tolerance, matching mesh
coordinates and allowing Blender's transform decomposition on save/reload.
Larger transform mismatches still reject publication and roll back Apply.
Rollback invalidates obsolete work before restoring runtime diagnostics, so cache
cleanup cannot overwrite the pre-operation statuses of mixed-mode neighbors.
Relevant errors include `STALE_SCENE_REVISION`,
`STALE_PATH_REVISION`, `STALE_FREE_EDIT`, `EDIT_IN_PROGRESS`,
`STRUCTURAL_IDENTITY_CHANGED`, `INVALID_FREE_PATH` and `INVALID_ATTACHMENT`.
Retain the journal: identical replay returns its receipt only when the live
postcondition still matches. Conflicting request IDs yield `REQUEST_ID_REUSED`;
changed postconditions yield `STALE_FREE_PATH_RECEIPT`.
Request identity is reserved durably across operation families before dispatch,
including native points/branches/recompute, profiles, anatomy and compatibility
operations. An exception releases only that attempt's new reservation as part of
journal rollback; existing successful reservations remain immutable.

Import/export and duplication preserve the graph, remap SCP/shared-point IDs and
destination coordinates, and allocate fresh sample/occurrence IDs for copies.
Missing required references reject import atomically without a fallback solve.
Editor recovery data is not part of VCP interchange.

## Output and runtime contract

Recompute resolves Free attachments and republishes (`FREE_UPDATED`) while
Controlled members of a mixed batch retain ordinary solver jobs. Invalid Free
attachments keep the last valid output marked stale/invalid. `FREE_UPDATED`
does not certify collision clearance or anatomical quality. A session/root/fiber,
mode and generation token rejects obsolete solver progress, final publication,
cache writes, status restoration and migration rollback after conversion.

Standalone Free recompute and direct property changes finish through the same
dependency dispatch as grouped/API requests. Terminal groups notify dependents
of successful and failed Free members once; a failed source retains its last
valid geometry and propagates stale state to ordinary lofts, transitive branches,
base/inflated meshes and mirrors. Immediate Free completion uses the runtime's
existing tail queue when another update is active, without recursively dispatching
the source or entering a planner/solver.

Free-containing ordinary lofts use the union of normalized source arc-length
stations to preserve every source corner without rewriting the fibers. Closed-loop
winding and cyclic starts are aligned on derived row copies before
union sampling; unequal sample counts are supported and source order is unchanged.
Exact structural tags locate branch roots; ambiguous repeated occurrences reject the
operation. Existing branch seams, mirror generation and inflation are reused.
Controlled-only loft preparation stays unchanged.
Public surface and muscle creation accept unequal saved Controlled node counts
when any source is Free, including unequal current sample counts. They validate
Free payloads and evaluate bounded candidate geometry before adding a surface
record. Controlled-only count restrictions and mixed OPEN/LOOP rejection remain.
Free LOOP patches retain every boundary sample during triangulation, including
collinear samples: an ear cannot clip a diagonal through another boundary sample.
Self-intersecting boundaries still reject the transaction.

Limits are 4,096 samples per Free fiber, 16,384 union stations per piece, and
262,144 generated vertices / 524,288 triangles per checked output assembly,
including derived mirror/base/inflation allocations. Preallocation rejection
reports `FREE_STATION_BUDGET` or `FREE_OUTPUT_BUDGET` with counts. No silent
downsampling or route repair occurs.

Export with `StaticScene.save_debug_copy`, then reopen normally. Source and
mirrored fibers must remain visible as normal curves, with native SCP colors in
Solid/Object mode. Geometry, persistence and debug visibility are separate checks.

## Verification and measured costs

`tests/blender/test_free_*.py` covers guarded creation/replay, conversion,
late publications, current-shape editing, stale/invalid drafts, rollback,
shared points, LOOPs, branches, mirrors, import/duplication and output limits.
`tests/unit/test_free_path.py` and `test_free_surface.py` cover pure identity,
deformation and sampling contracts. The real UI probe additionally exercises
native multi-object Edit Mode, subdivision, undo/redo, one-step Apply and shared
branch changes against actual base/inflated geometry.

Run from the selected checkout (the runner also pins child Blender imports):

```powershell
python tests/run_unit.py
blender --factory-startup -b --python-exit-code 1 --python tests/blender_runner.py -- --pattern=test_free*.py
blender --factory-startup --python tests/blender/free_fiber_ui_probe.py -- --output=E:/path/to/versioned-ui-evidence
blender --factory-startup -b --python tests/blender/free_fiber_probe.py -- --output=E:/path/to/versioned-geometry-evidence
```

The AF-24 repair-v003 technical fixture measured Blender 5.0.1 on Windows on
2026-09-21, including transactional output verification. The raw results are in
`maintenance/AF-24/repair_v003_geometry_01` under the external workflow directory.
Five warm repetitions follow one cold measurement; these are local observations,
not a speedup claim or an anatomical workload guarantee. Warm median / p95 in ms:

| Samples | Edit open | POLY extraction | Apply incl. capture | SCP deformation |
| ---: | ---: | ---: | ---: | ---: |
| 32 | 3.51 / 3.87 | 0.18 / 0.23 | 10.35 / 11.48 | 1.85 / 2.23 |
| 64 | 5.49 / 6.24 | 0.32 / 0.33 | 15.26 / 21.02 | 4.07 / 4.38 |
| 256 | 14.81 / 15.15 | 0.79 / 1.04 | 35.46 / 36.30 | 9.46 / 9.64 |
| 512 | 35.45 / 56.20 | 2.31 / 2.38 | 87.93 / 93.36 | 25.11 / 29.03 |
| 4096 | 229.27 / 301.25 | 12.65 / 25.15 | 583.56 / 701.71 | 187.64 / 207.92 |

Initial commit including capture measured 13.29, 13.35, 35.49, 92.36 and
507.94 ms respectively. A two-Free/two-Controlled branched fixture measured
capture 1.21 / 1.21 ms, native evaluation 0.85 / 0.86 ms, verified output rebuild
26.69 / 27.06 ms and forced preallocation rejection 0.47 / 0.49 ms.
The probe emits raw/cold/warm JSON, saved geometry, a recovery `.blend`, and a
normally reopened debug `.blend`; keep those versioned outside the repository.

Native editing/sampling references: [Blender curve structure](https://docs.blender.org/manual/en/latest/modeling/curves/structure.html),
[Spline API](https://docs.blender.org/api/5.0/bpy.types.Spline.html), and
[Bézier interpolation](https://docs.blender.org/api/5.0/mathutils.geometry.html#mathutils.geometry.interpolate_bezier).

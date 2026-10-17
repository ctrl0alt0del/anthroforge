# AnthroForge editing responsiveness and viewport clarity

Updated: 2026-10-15. Measurements: 2026-10-12. Status: analysis and proposed direction; this documentation work made no production behavior changes.

AnthroForge should remain comfortable to edit when final computation takes seconds. Treat input response, useful preview, final completion, and visual clarity as separate outcomes. The user requested this direction after repeated numerical optimizations still left production files slow, then requested viewport clutter as the next investigation.

The observed delays do not establish a computational ceiling. Some interruptions occur in synchronization, preparation, and publication even when no fiber solver iterations run. Improve those paths while keeping final geometry validation intact.

The [standalone application requirements](standalone_application_requirements.md) translate these findings into preferred application behavior and distinguish Blender integration boundaries from addon and product design choices.

## Existing capabilities

Build on these mechanisms instead of proposing them as new features:

| Capability | Existing implementation and scope |
| --- | --- |
| Deferred and coalesced requests | [sync_runner.py](../core/visualization/sync_runner.py) and the [runtime contract](runtime_contract.md). Selected event/source combinations receive quiet windows; this is not a universal interaction policy. |
| Native asynchronous fiber solving | [V3 batch coordinator](../core/vcp/v3/batch.py) and [native controller](../core/vcp/v3/native_controller.py). The AUTO policy does not send every small, isolated fiber edit through the batch path. |
| Priority and stale-result protection | [fiber_refinement.py](../core/visualization/fiber_refinement.py) prioritizes active/visible fibers, checks ownership and generations, retains some previous outputs, and separates previews from accepted output. |
| Background skin and topology work | [warm update jobs](../adapters/warm_update/jobs.py) use a persistent process; modal operators poll status and expose cancellation. |
| Pending surface dependencies | [surface_publication.py](../core/visualization/surface_publication.py) and dependency scheduling prevent consumers from treating unfinished parent surfaces as current. |
| Manual controls and progress | Soft tissues have Auto Recompute; overlap detection has Automatic and Refresh; skin/topology panels show stages and progress. These controls are separate rather than one editing policy. |
| Measurement | [fiber performance probes](fiber_performance_probe.md), request telemetry, and [shortcut_performance_probe.py](../tools/shortcut_performance_probe.py) already measure much of the relevant work. |

## Observed interruptions

1. **Shortcut setters run dependent work synchronously.** `_run_shortcut_sync` in [shortcut_edit.py](../app/use_cases/shortcut_edit.py) calls the immediate runtime path. The existing request debounce does not cover this shortcut source/event combination. Delaying that work requires preserving the complete shortcut override transaction and undo semantics, not simply moving its last function call into a timer.
2. **Background work has blocking preparation and publication.** [prepare_array_job](../adapters/warm_update/capture.py) bakes, captures, and serializes inputs before [start_update](../app/use_cases/warm_update.py) sets the starting status. Muscle capture, execution, and publication also run synchronously through [muscle_sync.py](../core/visualization/muscle_sync.py).
3. **Budgets cannot interrupt an indivisible operation.** Fiber and warning schedulers check time between units of work. A long capture or native initialization can exceed a nominal slice budget. The follow-up profile also found overlap capture/publication on the main thread after the shortcut returned.
4. **Coalescing the eventual job leaves repeated request costs.** Each muscle publication calls [remember](../core/muscle_pairs/capture.py), which requests an overlap refresh. [configuration.read](../core/muscle_pairs/configuration.py) reads the relationship document through validation and checksum handling. A profiled edit made 28 relationship-document reads. The job debounce happens after much of this bookkeeping.
5. **Concurrent editing needs consistent publication guards.** The October 12 inspection found only a root-existence check before skin/topology replacement. An October 15 source recheck found that [warm update publication](../app/use_cases/warm_update.py) now calls [job_revision.require_current](../adapters/job_revision.py), comparing the job's recorded epoch, scene/root identity, and change revision with current state and checking cancellation. The missing-guard finding is superseded. Qualify revision coverage and capture/publication timing before relying on unrestricted concurrent editing; this recheck did not rerun the earlier performance experiment.

## Production fixture evidence

The accepted runs used Blender 5.0.1 and `E:/development/WIP_models/skull_muscles.blend`: 175 objects, 19 SCPs, 24 Controlled fibers, and 12 muscles. The source SHA-256 was `4855042f259135c569c3e89b50df5d0441e6794bef5e774aebf924fd8372287e` and remained unchanged.

A hidden foreground Blender process ran the actual event loop. The initial unprofiled 1% Cranium Lobe Width change took 310.91 ms inside the setter. Telemetry recorded zero fiber solves/iterations, about 105.36 ms in SCP synchronization, 158.79 ms in the muscle driver, and 0.97 ms in the muscle numerical batch. These nested timings must not be added together.

The experiment retained every muscle publication and `remember` call, collected non-explicit overlap refresh requests across `publish_muscle_work`, and called refresh once per scene/root at batch exit. Solver settings and algorithms were unchanged. Both the defining module and the imported publication alias in `muscle_sync` were patched in the disposable process.

| Measurement | Existing behavior | Experimental batching |
| --- | ---: | ---: |
| First setter, 1.0 to approximately 1.01 | 302.00 ms | 193.90 ms |
| Second setter, approximately 1.01 to 1.0201 | 293.79 ms | 168.37 ms |
| First muscle driver | 156.79 ms | 43.45 ms |
| Second muscle driver | 158.75 ms | 45.94 ms |
| Final captured geometry hashes | 139 objects | All 139 matched |

This supports batching as a candidate for implementation. It does not establish smooth dragging, a frame-rate improvement, or general production readiness. There were only two consecutive edits per comparison process on one fixture. The separate cProfile run was used for attribution; its absolute durations are not comparable to the unprofiled timings above. A 100 ms timer heartbeat measures event-loop availability, not viewport FPS.

The geometry comparison covered mesh vertex coordinates, loop indices, face sizes and world matrices, plus curve point/Bezier control coordinates. It did not qualify every curve attribute, materials, visual appearance, undo, cancellation, or saved/reopened output. No source blend was saved. Startup/instrumentation failures were excluded from the comparison.

[Durable evidence](evidence/interaction_ux_2026-10-12.json) preserves accepted telemetry, fixture identity, geometry hashes, experiment/reference launch scripts, source fingerprints, and limitations. Existing uncommitted changes were present during the audit; the Git HEAD alone does not reproduce the tested working tree. The experiment remains outside production code.

## Proposed editing behavior

**Live, On Release, and Manual update modes.** Live keeps interactive updates for inexpensive work. On Release gives immediate control feedback and schedules expensive dependents after a gesture or committed numeric entry. Manual accumulates dirty edits until Update. A quiet window can support interactions without explicit gesture boundaries, but must not be mistaken for reliable mouse-release detection. Preserve one understandable undo action per gesture and allow newer edits to supersede obsolete work. Houdini uses these modes for complex procedural scenes; that is a useful precedent, not proof of AnthroForge effectiveness. [SideFX cooking documentation](https://www.sidefx.com/docs/houdini/basics/cooking)

**Responsive preparation and publication.** Acknowledge an operation before expensive preparation begins, then return to Blender so that feedback can draw. Capture Blender data in measured, bounded stages, move eligible numerical initialization to existing C++ workers, and budget the final Blender writes. A timer around a long synchronous operation is insufficient. Keep all Blender access on the main thread and send owned snapshots across the native/process boundary. Future optimization loops remain in C++; no per-iteration Python callbacks or silent Python optimizer fallback. [Blender threading guidance](https://docs.blender.org/api/5.0/info_gotchas_threading.html)

**Stable visible output while computing.** Keep the last accepted result visible with a clear pending/out-of-date state. Update the active control immediately and publish dependent results when ready. Reuse existing preview and generation mechanisms. An approximate deformation preview is a separate hypothesis requiring visual qualification; it must never become collision truth or feed final consumers as validated geometry. The current V3 runtime uses the final iteration budget even for interactive requests, so reducing an exposed interactive setting is not a complete solution.

**A shared responsiveness budget.** Coordinate input work, required dependencies, visible result publication, and advisory checks across the existing schedulers. Active-fiber priority already exists; the proposed difference is arbitration between subsystems and a total main-thread publication budget. Defer advisory checks during dragging without bypassing required collision, attachment, or stacking dependencies.

**Clear activity and control.** Show one compact activity summary with current stage, elapsed time, queued edits, and cancellation. Distinguish preparing inputs, solving, validating, and publishing. Counts such as “12 of 24 fibers” are useful but are not a reliable percentage of remaining time. Cancellation acknowledgement, actual worker termination, and discarding obsolete results are distinct events. Avoid promising pause/resume until the responsible backend supports it. [Progress control guidance](https://learn.microsoft.com/en-us/windows/apps/develop/ui/controls/progress-controls)

## Implementation order and acceptance

1. Qualify publication-batch refresh scheduling on representative production fixtures, including muscle-backed dependencies, mirrors, exceptions, and explicit refresh requests.
2. Add On Release/Manual interaction transactions and a consistent dirty/pending indicator, preserving existing Live behavior as an option.
3. Remove or subdivide the largest measured capture, initialization, and publication stalls. Qualify the output workers' input revision checks across editing, cancellation, undo, and loading.
4. Coordinate scheduler budgets and complete activity/cancellation behavior.
5. Test new approximate previews only where stable accepted output plus immediate controls is insufficient.

Initial proposed targets are input-response p95 below 50 ms and cancellation acknowledgement below 100 ms. These are design targets, not achieved guarantees. Measure actual viewport frame times separately and inspect the longest stalls as well as percentiles. Total completion time remains a separate metric so that responsiveness does not hide excessive starvation or delayed work.

Acceptance must include sustained dragging, typed changes, rapid successive edits, selection/orbit during computation, cold and warm runs, cancellation, deletion, undo/redo, and save/reopen on representative skull and body files. Record time to first useful feedback, longest blocked interval, final completion, stale-result rejection, and final geometry validation. Reuse existing telemetry and probes, extending them to real gestures and viewport timing where necessary. A dependency awaiting required stacking or collision output must remain visibly pending rather than silently accepting stale geometry.

## Next investigation is viewport clutter

The next design task is to make the viewport understandable while preserving anatomical context, reliable picking, and the established debug presentation. This section is an initial code inventory and a set of hypotheses; the clutter itself still needs inspection in actual production viewport views.

Existing controls already include:

- [Category Show/Hide](../ui/sections/category_visibility.py) for muscles and fibers. [Category ownership](../core/visualization/category_visibility.py) groups anatomical proxies and their controls together, including owned mirror proxies, using active-view-layer object hiding.
- [SCP isolation](../core/scp_runtime/visibility.py), which records and restores prior visibility in the scene/view layer.
- [SCP proxy view](../app/use_cases/proxy_view.py), which substitutes a scoped proxy and hides its contributors during a session. It is not a general live simplification layer for the whole avatar.
- [Active-fiber handle synchronization](../core/visualization/fiber_sync_runtime.py), which already limits endpoint/touch/loop handles to the active fiber and cleans up others. “Show controls only for the active fiber” is therefore not a new feature.
- [Handle display defaults](../core/visualization/fiber_sync_helpers.py) that draw handles in front of geometry. Whether this creates ambiguity at a particular view/zoom remains to be observed.

The most useful working hypothesis is **task-focused presentation with explicit context**, built on the existing visibility machinery. Compare a few reversible presentations for shaping bones, editing a fiber, inspecting muscle volume, and reviewing the finished surface. Within each, distinguish anatomical geometry, editable controls, and optional diagnostics. Geometry needed for context may remain visible while being excluded from ordinary picking. Decide how to expose source/mirror correspondence and pending output without adding labels and colors everywhere.

Before recommending or implementing presets, capture the actual viewport with overlays at identical camera positions and representative zoom levels. Inventory visible/pickable SCPs, source and mirrored fibers, base and inflated muscle surfaces, soft tissue, skin/topology, handles, attachment markers, and relationship/warning overlays. Test finding the active control, following a fiber to its support, judging volume, and returning to the previous presentation. Measure mistaken selections, visibility toggles needed, and editing latency as well as visual legibility.

Compare a small number of treatments against those tasks: independent helper visibility, active entity plus relevant anatomical context, and diagnostics shown on demand. These are unvalidated candidates, not accepted fixes. Preserve explicit user hiding and selection when entering/exiting focus; define view-layer versus per-viewport scope rather than mixing them. Blender's overlay controls are a relevant baseline for the comparison. [Viewport overlay documentation](https://docs.blender.org/manual/en/3.6/editors/3dview/display/overlays.html)

Temporary editing presentation must not leak into deliverables. Result blends must retain all current source and mirrored fibers in their normal curve display, native SCP colors in Solid/Object color mode, and the manual debug presentation of `skull_muscles.blend`. Use `StaticScene.save_debug_copy` for authoring exports and verify after reopening. Do not obtain a cleaner screenshot by saving render-only hiding, wire display, or uniform SCP recoloring.

### Three opacity states: default, hovered, selected

The user proposed increasing muscle transparency and extending the same three interaction states to fibers and SCPs. This is a candidate for the viewport-clutter comparison, not an implemented or performance-qualified feature. Selected takes precedence over hovered, which takes precedence over default. Keep each SCP's native RGB identity and use role-specific opacity values: thin fibers may need a higher default opacity than broad muscle surfaces to remain traceable. Selected surfaces must still allow the anatomy needed for the current editing task to be read; maximum opacity is not automatically the best selected value.

There is already partial support. [Muscle material setup](../core/visualization/muscle_sync_helpers.py) assigns base-surface alpha 0.35/0.45 and inflated-surface alpha 0.65/0.80 for inactive/active states, then copies that color to the object. [Fiber selection highlighting](../core/visualization/fiber_sync_runtime.py) already changes active-fiber color. The proposed difference is a consistent display policy across all three entity types, a hover state, and a narrowly scoped update path. Reusing muscle material setup on mouse movement would unnecessarily repeat material-slot writes.

Blender documents per-object alpha for Workbench object colors. A disposable Blender 5.0.1 Workbench render test with two overlapping planes confirmed visibly different results at alpha 1.0, 0.6, and 0.2 with global X-Ray disabled. Setting object alpha generated a shading-only dependency-graph update in that isolated scene, including when assigning the same value. This establishes a supported rendering mechanism, not its production-frame cost or the behavior of every AnthroForge handler. [Blender viewport display documentation](https://docs.blender.org/manual/id/5.0/render/workbench/display_settings.html) and [reproducible probe evidence](evidence/viewport_opacity_2026-10-12.json).

Keep three costs separate:

| Cost | Existing evidence | Proposed experiment or difference |
| --- | --- | --- |
| Tracking and applying state | Active selection and color updates already exist. Alpha writes still emit shading updates. Some addon handlers traverse objects even when geometry did not change. | Keep transient hovered identity and selected identities; write only when the resolved state changes, to the old/new entity's display objects. Confirm no solves, geometry invalidation, material recreation, or amplified synchronization from these writes. |
| Finding the hovered entity | [The current picker](../core/scp_runtime/viewport_picker.py) caches candidates but raycasts every candidate mesh for each query; its SCP candidate classification excludes curves. [Touch preview](../operators/fiber_tools.py) skips identical mouse coordinates but has no time throttle. | Coalesce movement to the latest pointer position and initially cap hover queries at about 20 Hz. Cache a spatial/bounds shortlist and test only relevant candidates. Measure whether this is sufficient before building a more complex picker. |
| Drawing transparency | The isolated rendering test verifies appearance, not frame time in overlapping anatomy. | Compare static transparency against the original production view before enabling hover. More visible overlapping surfaces may increase GPU work and visual ambiguity even with no picking cost. |

Mouse movement should only record the latest position; a bounded hover service resolves it. Run no picking while the pointer, view, and published geometry are unchanged. Refresh after orbiting or geometry publication even when the pointer stays still. Initially suspend hover during navigation and active transforms, then resolve it when the gesture ends. A timer or a 20 Hz cap does not bound the duration of an individual raycast pass; measure cold-cache and first-query-after-edit stalls as well as warm queries.

The hover service should share existing entity/source/mirror mapping, but must define curve picking separately. A cached fiber centerline with a screen-space hit tolerance is a hypothesis to compare against native evaluated-curve picking. Do not convert every curve to a mesh or rebuild acceleration data on each mouse movement. Account for zoom, view changes, geometry revisions, deletion, undo, and visibility changes when invalidating caches. Repeated numerical geometry acceleration belongs in the existing native infrastructure when required; Blender data access remains on the main thread.

Picking policy is part of the UX. A transparent muscle can still be the nearest geometric hit and prevent a visible fiber behind it from becoming the hover target. Test explicit editing-category filters and a deliberate way to choose deeper targets. Hover should predict the entity that a click will select; preserve the same policy for both. Do not infer pickability from the current opacity, since changing opacity would then change the target and could cause flicker. A small movement tolerance or brief hysteresis is a candidate if thin curves and overlapping boundaries cause unstable hover.

Keep hover out of authored SCP properties, selection changes, and undo history. Apply temporary display overrides over canonical colors so ordinary synchronization cannot erase the interaction state or save it as the new base color. Object colors are shared across viewports displaying the same object, so an initial object-color implementation needs one explicit hover owner; truly independent per-viewport appearance would require a different drawing path. Define restoration for tool exit, addon disable, file loading, and saving/exporting so transient hover cannot leak into deliverables.

Qualify in three stages on the same production camera views: existing presentation; default plus selected opacity without hover; then the identical opacity policy with hover enabled. Record viewport frame times, hover query time and response latency, handler/runtime activity, and mistakes selecting visible targets behind transparent surfaces. Test dense overlaps, source/mirror pairs, fibers at different zooms, selection/orbit while computation is pending, and first movement after geometry changes. If static transparency improves legibility but hover exceeds the interaction budget, retain default/selected states and test hover only within an explicit editing tool. Neither a production speedup nor a clutter reduction has yet been demonstrated for this proposal.

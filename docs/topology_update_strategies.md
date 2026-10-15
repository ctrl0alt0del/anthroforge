# Topology update strategies

New final-skin references use native **LE by default**, with **FAST** selectable in
Output Update. Both use the existing versioned strategy pipeline. Once construction
and reference preparation succeed, updates change only final-mesh coordinates;
they do not require a draft mesh, draft bindings, or topology regeneration.
Older files remain unchanged until explicitly initialized or rebuilt. Their legacy
`current` strategy remains available. Unknown methods never select a fallback.

## Persistent final-skin flow

Topology construction prepares a tetrahedral proxy, material sample addresses,
embedding, stable vertex IDs and symmetry correspondence before publication.
The immutable versioned reference is checksummed and packed into a Blender Text
datablock, associated with both root and final mesh through datablock pointers.
Only successful reference publication removes the temporary draft and its bindings.
Failed replacement preparation retains the previous final output; failed first
preparation retains usable construction outputs for retry.

Native preparation uses proxy resolution 48, constraint strength 100, and 128 FAST
handles. Each root has a persistent background service. Updates debounce for
300 ms, cancel obsolete work, and reject stale reference/settings/anatomy revisions.
LE/FAST always solve from the immutable reference. Cached BBW products are disposable,
checksummed and reconstructible; the packed reference never depends on their files.
The Windows service memory ceiling is the smaller of 8 GiB and half the available
memory at launch. Cancellation terminates an unresponsive service after two seconds.

The contact stage projects unilateral constraints from reference to proposal, with
symmetry inside its iterations. It separately checks motion from the displayed pose,
so correction is independent of previously displayed positions. Separate vertex
identities may touch at zero separation. Correction has bounded iterations/time;
remaining crossings, unresolved contact, proxy inversions and solver limits are
quality warnings. Coplanar continuous-motion coverage remains incomplete and is
reported explicitly. Sampled nearest-normal anatomical clearance is reported
separately and is not a full volume-containment guarantee. Initial scalar extraction
still needs resolvable gaps to construct distinct sheets.

Use **Initialize Deformation Reference** for existing topology, **Update Now** for
the selected method, or **Rebuild Skin & Topology** to explicitly replace connectivity
and the reference. Construction-setting edits mark construction stale. Shape keys,
armature modifiers, shared mesh data, invalid sample addresses and incompatible
contributor changes preserve the previous mesh and report actionable issues.
UVs, attributes, object identity and mesh connectivity survive ordinary updates.

## Legacy selection and fallback

Legacy updates without a deformation reference default to `current` and `REBUILD`. Experimental updates use
`STOP`: a failed topology update or classified topology rebuild cannot regenerate
topology. The issue-system integration checkpoints completed skin and may publish
it as a partial result while retaining the old topology as stale. Quality findings
alone are warnings; malformed data and missing consumer contracts still stop.
Preparing missing bindings is a separate operation;
`PREPARE` is rejected in STOP mode. Skin regeneration itself remains permitted.

The Blender operator accepts:

```python
bpy.ops.af.update_skin_topology(
    strategy="current", strategy_version=1, failure_policy="STOP")
```

`app.use_cases.warm_update.start_update(context, topology_update=options)` also accepts
an options dictionary. Fields are `strategy`, `version`, `module`, `failure_policy`,
`settings`, and optional `maximum_surface_error` (a distance in scene units).
The job protocol is version 5; versions 2â€“4 jobs load with compatible defaults.
Selection is per job and travels through the worker protocol. Both the array and
Blender workers use `workers.topology_update.attempt_update`. Direct Blender topology
adapters use the same core strategy pipeline.

## Contract

`core.warm_start.strategy_model.TopologyUpdateContext` provides the old topology,
before and after skins, topology capture (including guides and symmetry plane),
skin update kind, settings, cancellation check, and worker memory budget. Array
inputs are read-only views. Existing bindings are copied before calling the legacy
solver, which can mutate them. Dictionaries are copied. This is protection against
accidental modification, not a sandbox for untrusted plugins.

The worker supplies current contributor geometry in `after_sources`. Previous
contributor geometry is optional and is not reconstructed from the old skin;
strategies needing `before_sources` must capture it explicitly and reject missing
inputs. Full field grids are not serialized by this change. A field strategy must
request or construct the appropriate field samples within its memory budget.

`solve(context)` returns a `TopologyUpdateCandidate` with:

- Updated positions in the original vertex order and matching `vertex_ids`.
- Skin and guide bindings for the next update.
- Acceptance status and an explanatory message.
- JSON diagnostics and optionally a versioned, JSON-serializable deformation description.

Vertex IDs currently mean the accepted topology's index order, `0..N-1`; this does
not introduce a new cross-remesh identity system. Candidates cannot supply faces.
The pipeline retains the input faces, region IDs, ownership, and density attributes.

For a separate experimental implementation, put a module on the worker's Python
import path and export `STRATEGY`, an object with `name`, `version`, and `solve`.
Select its module explicitly in the job options. Reserved `current` cannot be
overridden this way. In-process tests may inject an implementation directly into
`run_topology_strategy(context, options, strategy=...)`.

Python implementations should only orchestrate native code. New iterative fitting,
registration, and optimization must execute as batched C++ calculations using the
existing native build/load infrastructure. The `current` adapter retains the
pre-existing numerical implementation; this refactor is not a numerical migration.

## Shared acceptance and diagnostics

The pipeline records input validation reports and checks vertex count/order, finite positions,
binding sizes/indices/barycentric coordinates, quad connectivity properties,
degeneracy, orientation relative to the reference, and requested symmetry.
It records distance to each vertex's bound point on the target skin, offset-aware
binding residuals, runtime, and worker process memory counters. An optional shared
`maximum_surface_error` reports a quality warning above that bound-point distance.
That distance is not an exact closest-surface or Hausdorff distance. The default
records it without introducing a new fit cutoff into the existing algorithm.

The inherited orientation test is not a general large-rotation inversion test.
Native self-intersection diagnostics report proper crossings separately from contact
and retain bounded witnesses; unavailable diagnostics mean unknown quality. The core
pipeline does not certify bidirectional surface coverage. The actual torso diff
experiment additionally uses a common native nearest-surface check and sampled
reverse coverage. An accepted update means usable data, not passed geometry quality.

### Contact and separation: required behavior (2026-10-14 clarification)

The user permits a visible gap to close when the opposing skin surfaces remain
topologically distinct. Thin thighs may have an air gap; fuller thighs may touch.
Both must retain their own surface vertices and faces, without welding, deleting a
contact sheet, or introducing faces across the contact. This does not require two
separate mesh objects: both thighs belong to the same connected body surface.

For updates, preserve vertex identities and face connectivity through an
open-to-contact-to-open sequence. Verify that separation reopens without rebuilding
topology. Surface contact is permitted; penetration, inverted/collapsed faces, and
unintended bridges remain separate failures. A numerical contact tolerance must be
distinguished from a user-visible minimum air gap and reported explicitly.

This is an acceptance target, not an implemented contact guarantee. The strategy
interface already retains faces, but shared validation lacks full self-contact
classification. Initial skin generation has no accepted topology to preserve;
it must establish and retain the identity of opposing surface patches. Removing
the field's positive-clearance gate alone does not supply that capability.

Input array storage is checked against the memory budget before execution. Native
strategies must additionally enforce their working-allocation budgets and cancellation.
The current adapter checks cancellation around its existing solve; it does not add
iteration callbacks. Reported peak memory is the worker process lifetime high-water
mark, so use fresh replay processes for comparative memory measurements.

The worker writes `topology_strategy.json` before handling rejection. Successful
results carry strategy identity/version/settings, configuration signature, shared
metrics, and optional deformation metadata through result serialization and Blender
publication. Failures under STOP retain the previous scene outputs. REBUILD records
the rejected strategy's reason before invoking the existing topology generator.

Replay tools, experimental methods, and historical measurements are preserved on
the `experiment-damp` branch. Production regression tests have no dependency on
that branch’s experiment modules.

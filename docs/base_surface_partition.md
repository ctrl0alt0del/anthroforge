# Local shared-border repair

`anatomy.partition_base_surfaces` explicitly repairs two adjacent open loft strips
intended to share a local border. It divides their overlap along a common middle
border without separating whole heads or introducing a clearance gap. A groove
after separate inflation is acceptable; inflation derivatives are not blended.

Use it before inflation. This is not a closed-volume Boolean, arbitrary mesh
remesher, bone-collision repair or automatic anatomical adjacency detector.

## Standalone operation

Use a normal authoring 0.4 request with these parameters:

```python
params = dict(
    scene_id=scene_id, expected_scene_revision=revision,
    paths=[first_rows, second_rows],  # two arrays: rows × samples × world XYZ
    sides=[1, 0],                   # 0 = first row, 1 = last row
    settings=dict(
        along_axis=[0, 1, 0], across_axis=[1, 0, 0],
        blend_distance=0.25, max_displacement=0.2,
        max_depth_gap=0.1, max_outline_error=0.002))
```

Example lengths are scene units, not anatomical defaults. Each strip has 2–8
ordered rows, each containing 2–1,025 samples; total input budget is 8,192 points.
Rows within a strip have equal sample counts and run monotonically along the
axis. The two strips may run in opposite directions. Their facing sides must
have interiors on opposite sides in this local chart. For wrapping geometry,
select a suitable local patch rather than forcing a global projection.

The returned asset contains repaired `paths`, material `stations`, actual native
`meshes`, limits/measures and mechanical validation. Retain those stations when
creating Free lofts: independent arc-length normalization changes the surface.
This operation does not mutate Blender objects. Inline geometry is an immutable
calculation snapshot, not a live reference to scene objects.

For an existing native branch, optionally pass:

```python
connection = dict(main=0, side=0, root_indices=[50, 54])
```

These are input main-boundary sample indices, one per child row. Child rows must
start at those roots. The operation protects and remaps them, conforms sampling
at tessellated contacts, and checks the actual branch assembly. Omitting an
existing connector checks ordinary lofts and can reject their unconstrained
root chords. Native branch topology is unchanged.

In a repaired smooth-base asset, `base` and `native` are the repaired geometry;
`pre_partition_base` and controls marked `pre_partition_fit_only` retain the
initial fit for audit. Downstream construction must use the repaired paths and
stations rather than reevaluating those initial controls.

## During creation

`anatomy.smooth_base_preview` accepts an optional explicit list:

```python
overlap_repairs = [dict(
    patch_ids=['head_a', 'head_b'], sides=[1, 0], settings=repair_settings)]
```

Repair runs after fitting/attachment and before final validation.
`smooth_base_publish` publishes the repaired Free paths and material stations
through the existing atomic transaction. Shape-change limits still apply.
Patches may appear in only one repair pair; existing shared-fiber aliases in
repaired patches are rejected rather than silently breaking ownership. Omission
leaves creation unchanged. Existing muscles are not silently rewritten.

Coincident partial borders are geometric contacts, not new live shared-fiber
constraints. Existing branches retain their shared roots. Recheck contact after
independent curve editing or skeletal deformation. Complete shared borders still
use the existing `seams` contract with a single shared Free fiber.

## Calculation and limits

C++ synchronizes longitudinal sections, detects overlapping facing borders in
the chart and replaces both by their midpoint curve through each overlap. Depth
changes blend near interval ends; displacement falls to zero at opposite outer
borders. Separate overlap intervals are supported. Separated borders stay apart.

The operation rejects nonmonotone charts, side-order inversions, excessive depth
separation/displacement, attachment conflicts and excessive outline resampling
error. Endpoints remain exact. Synchronization can approximate skewed end spans
even where outer-border displacement is zero. `outer_border_resampling_error`
measures bidirectional vertex-to-polyline error; `max_outline_error` gates it.
The result is piecewise smooth, not guaranteed C1 or minimum tessellation.

Assembled crossings and collapsed triangles gate readiness. These are finite
checks, not an exact intersection certificate. Anatomy, SCP clearance and
inflation remain separate checks. There is no Python optimizer fallback.

## Evidence

The September 24 biceps ablation had five cross-head intersections. Repair kept
four Free paths and the existing branch root: zero detected assembled crossings
or collapsed triangles. Maximum intended border movement was 0.12045 scene units;
outline resampling error was 0.01171, within the explicitly selected 0.015 limit.
This verifies local base repair, not whole-muscle acceptance or inflation.

Tests cover overlap lenses, reversed directions, disjoint intervals, separated
borders, rigid transforms, locked endpoints and geometry limits. Blender tests
cover explicit/automatic calls, native publication, replay, save/reload, visible
normal curves, stale requests and shared ownership, alongside existing smooth
base rollback, editing and deformation regressions.

# Draft skin

AnthroForge draft skin is a disposable, closed preview shell generated from the
finalized SCP and VCP surfaces of one `AF_ROOT`. It is not retopology and does
not contain UVs, skin weights, or a game-ready edge layout.

## User workflow

1. Set each SCP's **Draft Skin Collagen** mode:
   - **Auto** gives ear, cartilage, and nasal names collagen `0`; other SCPs use
     `1`.
   - **Uniform** uses the SCP's scalar collagen value.
   - **Painted** reads absolute weights from `AF_SKIN_COLLAGEN`; unassigned
     vertices inherit the scalar value.
2. Adjust the root's four model-relative field controls when the default skin
   envelope needs to be tighter, deeper, or spread over a different radius.
3. Use **Paint Collagen** to initialize and activate the vertex group. Blue is
   absolute collagen `0`; red is absolute collagen `1`. Native Blender brushes,
   gradients, and blur remain available.
4. Press **Generate Draft Skin**. The panel reports the background stage and
   progress; **Cancel** or Escape stops the worker.

**Minimum Skin Distance** is the required offset from all contributors.
**Maximum Collagen Depth** is additional distance beyond that minimum.
**Collagen Core Radius** preserves painted values near the SCP, and
**Collagen Falloff Width** controls their transition back to full collagen.
All four values are percentages of the captured model's longest axis.

The previous draft skin is retained until the replacement has passed validation
and imported successfully. Failed and cancelled job logs are shown in the panel
and retained until the next job or addon shutdown.

## Architecture

- `core/draft_skin` contains only the data contracts, versioned protocol,
  numerical field construction, meshing, and validation.
- `adapters/draft_skin` contains Blender capture/output, worker-process
  orchestration, and vendored dependency loading.
- `app/use_cases/draft_skin.py` coordinates the adapters.
- `operators/draft_skin.py` owns only Blender modal behavior.
- `workers/draft_skin_worker.py` opens a temporary scene copy, bakes the
  dependency runtime, captures finalized contributors, and runs the solver.

The foreground operation only writes a fast temporary `.blend` copy and polls
atomic status files. Baking, capture, dependency loading, and solving all run in
a factory-startup background Blender process.

## Contributor rules

Capture is root-scoped and independent of object visibility. It includes SCP
originals and generated mirrors, final muscle `INFL` surfaces, final blobs, and
standalone fibers. A fiber consumed by a muscle is included only when that
muscle has no valid final surface. Muscle `BASE`, controls, handles,
intermediates, unrelated geometry, and existing draft skins are excluded.

Mirrors reuse the source SCP's collagen array when evaluated vertex counts
match. A mismatch uses the uniform fallback and records a warning.

## Numerical pipeline

The longest source axis uses 220 cells when memory permits. Padding is derived
from the authored envelope and falloff plus a fixed safety margin. The worker
lowers the resolution no further than 160 cells when the estimated peak exceeds
the smaller of 4 GiB and 35% of available RAM.

Triangle surfaces are sampled in grouped, vectorized batches. Exterior
accessibility and Euclidean distance transforms produce:

- a required SCP+VCP envelope;
- a wider SCP rest envelope;
- a sixteen-level, smoothly decaying collagen field.

The final implicit field is

`required + collagen * (full_rest - required)`.

The native local-gap stage evaluates the protected field on a shared fine
lattice. Lewiner marching cubes extracts its zero surface. Source-supported
components are retained, oriented outward, and receive eight constrained
`0.45/-0.47` smoothing passes. Source coverage and protected gaps are validated
before publication.
Collagen is sampled back onto the output's point-domain
`af_skin_collagen` attribute.

### Contact-permitted gap validation

Native build `af_fiber_ccd_v3_55.dll` provides gap-validation capability v2.
Both protected separator and exterior-corridor samples may lie on the skin
surface or arbitrarily close to it from outside. The previous final-validation
requirements of `1.5h` and `1.75h` empty radius have been removed. A sample
strictly inside solid skin still fails, as do exposed source vertices and
source-skin crossings. Minimum clearance remains a diagnostic statistic;
zero is allowed. Boundary classification uses only a floating-point tolerance
derived from coordinate precision, not a voxel-based minimum gap width.

Generation and geometry-only warm revalidation use the same native predicate.
Results record `gap_validation_policy=contact-permitted-v2`; solver version
`native-local-gaps-5` and gap-signature version 2 invalidate older cached skin
when generation/update is requested. Opening a file does not regenerate it.
Old native libraries are rejected before work, preserving previous output.

This changes validation only. Field construction still carves finite corridors
and reserves fine samples around protected gaps. The validator samples those
original constraints; it is not a continuous collision detector or a proof of
separate-sheet identity at arbitrary contact. In particular, the existing
watertightness/orientation checks do not prove absence of self-intersections.
The regression suite tests exact contact between distinct closed components,
sub-voxel openings, solid bridges, scaling, translation, warm revalidation,
cache invalidation, and native capability rejection.

### Native field memory

Native build `af_fiber_ccd_v3_54.dll` provides compact-field capability v1.
Uniform 32-cubed tiles retain one exact value; varying tiles allocate float
arrays on demand. X/Y sphere-distance propagation runs in independent Z slabs.
Only intermediate columns that can influence the final target domain survive
into the Z pass. Propagation-only tiles outside the coarse envelope are
released before final classification, and uniform finished tiles are compacted.
Read-only output-validation BVHs omit the duplicate face-index bounds table
used for refitting mutable snapshots; source and runtime snapshots retain it.
Positive intermediate distances must remain exact: the exterior-corridor tests
interpolate the field before the final clamp.

This applies sparse-storage ideas from
[topology-adapted octree offsets](https://daniel-zint.github.io//publication/2023-07-04-Feature-Preserving-Offset-Mesh-Generation-from-Topology-Adapted-Octrees)
and [constant-region storage](https://www.openvdb.org/documentation/doxygen/overview.html).
It does not introduce adaptive voxel spacing or change gap thresholds, collagen,
source coverage, marching cubes, or smoothing. Fine-grid work and flag storage
still depend on the smallest protected gap.

Statistics distinguish resident/peak field arrays, auxiliary field storage,
logical samples, and process memory. The native-field budget does not represent
total process RAM: input geometry, BVHs, output meshes, and validation also use
memory. Allocation failures retain the previous output. Varying-field budget
errors report the budget, lattice dimensions, and voxel spacing.

`tools/draft_skin_memory_probe.py` replays a saved capture against an explicit
native DLL. The October 12 rib-radius capture reproduced the old propagation
failure at 512 MiB. Compact storage completed that field at the same budget and
produced byte-identical raw and smoothed meshes against the original build,
including production component filtering and outward orientation. Retained
field storage fell from 506 MB to 211 MB; peak process resident memory fell
from 1.78 GB to 1.47 GB. The final paired replay took 219 seconds originally
and 240 seconds with compact storage (9% slower); earlier diagnostic timings
varied. Both builds still reported six protected-gap violations and failed
watertightness/orientation checks on that capture. It is a memory regression
fixture, not an accepted anatomical skin result. Binding and publication were
not run after failed geometry validation.

## Protocol and dependencies

Jobs use protocol-v4, `allow_pickle=False` `input.npz` and `result.npz`
files plus atomically replaced `job.json` and `status.json`. `job.log` is
append-only and `cancel.request` is the cancellation signal.

Windows x64 CPython 3.11 wheels and their license files are stored under
`vendor/draft_skin/wheels`. `vendor/draft_skin/manifest.json` pins every file
by SHA-256. The offline release builder verifies each wheel and its `RECORD`,
then expands dependencies and native libraries into the add-on ZIP at
`vendor/draft_skin/bundles/win64-cp311-v2`. The release ZIP omits the source
wheels but retains wheel metadata, licenses, and a locked hash for every
installed bundle file. The worker validates the complete bundle before
modifying its module search path. Generated `__pycache__/*.pyc` files are allowed
only when their corresponding Python source is in the verified inventory.
The bundle's Python modules load directly from verified source, bypassing those
caches without reading, writing, or deleting them. Missing files, altered source
or native libraries, links, and other unexpected files still fail validation;
inventory errors identify the offending paths and counts.
It does not download, run pip, or extract a
runtime cache. Temporary job input/output is separate and still uses TEMP.

Build the installable ZIP with `python tools/package_addon.py --output
dist/anthroforge-win64-cp311.zip` on a packaging host with the pinned wheels.
The adjacent `.zip.json` records the ZIP SHA-256 and bundle lock. Install the
ZIP as the add-on in Blender 5.0.1 on Windows x64 with CPython 3.11 and host
NumPy 1.26.4. An editable checkout intentionally has no expanded dependency
tree; with Blender and its workers closed, developers may explicitly run
`python tools/build_draft_skin_vendor.py --in-place` once. Never run that
command during a Draft Skin job. A missing or damaged bundle fails with a
reinstall instruction. To upgrade, close Blender and all workers, replace the
entire installed add-on, then generate again; hot-swapping loaded binaries is
unsupported. Refreshing wheel or bundle hashes requires a version bump,
removal of the previous `bundle_lock_sha256`, and `--refresh-lock
--previous-bundle <old-id>` on an empty build target. Review and commit the
new printed lock value before packaging.

## Output contract

The result is `AF_OUTPUT/AF_DRAFT_SKIN` with:

- `af_draft_skin`
- `af_root_name`
- `af_skin_input_hash`
- `af_skin_solver_version`
- `af_skin_stats_json`
- `af_skin_source_map_json`
- point attribute `af_skin_collagen`

The result is not registered with the live dependency runtime. Regeneration is
always explicit.

## Visual acceptance

`tools/draft_skin_acceptance.py` runs the real asynchronous workflow, saves the
result, and renders structure-only, skin-only, and overlay views. With a
reference blend it requires relative volume below 1% and the bidirectional P99
vertex-to-surface distance below `1.5h`; it also reports the strict maximum as a
diagnostic for localized bake-state differences.

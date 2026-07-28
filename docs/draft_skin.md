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

Lewiner marching cubes extracts the zero surface. The largest connected shell
is retained, oriented outward, and receives eight `0.45/-0.47` Taubin passes.
Collagen is sampled back onto the output's point-domain
`af_skin_collagen` attribute.

## Protocol and dependencies

Jobs use protocol-v2, `allow_pickle=False` `input.npz` and `result.npz`
files plus atomically replaced `job.json` and `status.json`. `job.log` is
append-only and `cancel.request` is the cancellation signal.

Windows x64 CPython 3.11 wheels and their license files are stored under
`vendor/draft_skin/wheels`. `vendor/draft_skin/manifest.json` pins every file
by SHA-256. The worker verifies every wheel before extracting it into a
versioned temporary cache; the interactive Blender process never changes its
module search path.

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
